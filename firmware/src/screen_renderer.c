#include "screen_renderer.h"
#include "screen_font.h"
#include "vendor/qrcodegen.h"
#include <string.h>
#include <stdio.h>
#define C_BG 0x0083
#define C_PANEL 0x08C5
#define C_MUTED 0x74B3
#define C_WHITE 0xEF9F
#define C_LINE 0x1988
typedef struct { uint16_t *pixels; int width,height; } canvas_t;
static void screen_pixel(canvas_t *c, int x, int y, uint16_t color) {
  if (!c->pixels || x < 0 || x >= c->width || y < 0 || y >= c->height) return;
  c->pixels[y * c->width + x] = color;
}

static void screen_rect(canvas_t *c, int x, int y, int w, int h, uint16_t color) {
  for (int py = y; py < y + h; ++py)
    for (int px = x; px < x + w; ++px) screen_pixel(c, px, py, color);
}

static void screen_circle(canvas_t *c, int cx, int cy, int radius, uint16_t color) {
  for (int y = -radius; y <= radius; ++y)
    for (int x = -radius; x <= radius; ++x)
      if (x * x + y * y <= radius * radius) screen_pixel(c, cx + x, cy + y, color);
}

static void screen_draw_icon(canvas_t *c, screen_ui_view_t view, int phase, int center_x, int center_y) {
  const int cx = center_x, cy = center_y;
  screen_circle(c, cx, cy, 37, view.accent);
  screen_circle(c, cx, cy, 32, C_PANEL);
  switch (view.icon) {
    case SCREEN_ICON_LISTENING:
      screen_rect(c, cx - 3, cy - 17, 6, 24, C_WHITE);
      screen_circle(c, cx, cy - 17, 3, C_WHITE);
      screen_rect(c, cx - 9, cy + 3, 3, 8, C_WHITE);
      screen_rect(c, cx + 6, cy + 3, 3, 8, C_WHITE);
      screen_rect(c, cx - 9, cy + 9, 18, 3, C_WHITE);
      screen_rect(c, cx - 1, cy + 12, 3, 6, C_WHITE);
      screen_rect(c, cx - 7, cy + 17, 15, 3, C_WHITE);
      break;
    case SCREEN_ICON_THINKING:
      for (int i = 0; i < 8; ++i) {
        int dot = (i + phase) & 7;
        static const int dx[8] = {0,18,26,18,0,-18,-26,-18};
        static const int dy[8] = {-26,-18,0,18,26,18,0,-18};
        screen_circle(c, cx + dx[i], cy + dy[i], dot == 0 ? 5 : 3, dot < 3 ? view.accent : C_MUTED);
      }
      break;
    case SCREEN_ICON_SPEAKING:
      for (int i = 0; i < 7; ++i) {
        int h = 8 + ((i * 7 + phase * 5) % 19);
        screen_rect(c, cx - 22 + i * 7, cy - h / 2, 4, h, C_WHITE);
      }
      break;
    case SCREEN_ICON_ERROR:
      screen_rect(c, cx - 3, cy - 19, 6, 25, C_WHITE);
      screen_circle(c, cx, cy + 14, 4, C_WHITE);
      break;
    case SCREEN_ICON_IDLE:
    default:
      screen_circle(c, cx, cy, 17, view.accent);
      screen_circle(c, cx, cy, 12, C_PANEL);
      screen_circle(c, cx, cy, 6, view.accent);
      screen_circle(c, cx - 23, cy, 3, C_WHITE);
      screen_circle(c, cx + 23, cy, 3, C_WHITE);
      break;
  }
}


/* Wrap UTF-8 only at codepoint boundaries; explicit newlines remain meaningful. */
static bool text(canvas_t *c,const char *s,int cx,int y,int max_width,screen_font_size_t font,uint16_t color) {
 if(!s)return false;
 bool ok=true;
 while(*s) {
  if(*s=='\n'){s++;y+=15;continue;}
  char line[128];size_t n=0,last_space=0;const char *start=s,*after_space=NULL;
  while(*s && *s!='\n') {
   unsigned char lead=(unsigned char)*s;
   size_t bytes=lead<128?1:(lead&0xe0)==0xc0?2:(lead&0xf0)==0xe0?3:(lead&0xf8)==0xf0?4:0;
   if(!bytes)return false;
   for(size_t i=1;i<bytes;i++)if(!s[i] || ((unsigned char)s[i]&0xc0)!=0x80)return false;
   if(n+bytes>=sizeof(line)) return false;
   memcpy(line+n,s,bytes);line[n+bytes]=0;
   int measured=screen_font_measure(font,line);
   if(measured<0)return false;
   if(measured>max_width) {
    if(!n)return false;
    if(after_space){n=last_space;s=after_space;}
    break;
   }
   if(*s==' '){last_space=n;after_space=s+1;}
   n+=bytes;s+=bytes;
  }
  if(s==start)return false;
  line[n]=0;
  if(y+14>c->height)return false;
  ok &= screen_font_draw_centered(c->pixels,c->width,c->height,cx,y,font,line,color);
  if(*s=='\n')s++;
  while(*s==' ')s++;
  y+=15;
 }
 return ok;
}
static bool setup(canvas_t *c,const char *ssid) {
 static char cached[33];static uint8_t qr[qrcodegen_BUFFER_LEN_FOR_VERSION(3)];
 if(!ssid || !*ssid || strlen(ssid)>32 || strpbrk(ssid,"\\;,:\"")) return false;
 if(strcmp(cached,ssid)) {
  char payload[64];uint8_t tmp[qrcodegen_BUFFER_LEN_FOR_VERSION(3)];
  snprintf(payload,sizeof(payload),"WIFI:T:nopass;S:%s;;",ssid);
  if(!qrcodegen_encodeText(payload,tmp,qr,qrcodegen_Ecc_MEDIUM,3,3,qrcodegen_Mask_AUTO,true)) return false;
  strcpy(cached,ssid);
 }
 bool wide=c->width>c->height;int left=wide?5:12,top=wide?12:36;
 for(int y=0;y<111;y++) for(int x=0;x<111;x++)
  c->pixels[(top+y)*c->width+left+x]=qrcodegen_getModule(qr,x/3-4,y/3-4)?0:0xffff;
 if(wide) return text(c,"НАСТРОЙКА",177,16,112,SCREEN_FONT_HINT,0xF5A8) && text(c,"ТОЧКА ДОСТУПА",177,42,112,SCREEN_FONT_SMALL,C_WHITE) && text(c,"192.168.4.1",177,68,112,SCREEN_FONT_SMALL,C_WHITE);
 return text(c,"НАСТРОЙКА",67,8,125,SCREEN_FONT_HINT,0xF5A8) && text(c,"ТОЧКА ДОСТУПА",67,159,125,SCREEN_FONT_SMALL,C_WHITE) && text(c,"192.168.4.1",67,180,125,SCREEN_FONT_HINT,C_WHITE);
}
bool screen_render(uint16_t *pixels,int width,int height,const screen_render_model_t *m) {
 if(!pixels || !m || !((width==135 && height==240)||(width==240 && height==135))) return false;
 canvas_t value={pixels,width,height},*c=&value;
 for(int i=0;i<width*height;i++) pixels[i]=C_BG;
 if(m->setup) return setup(c,m->ssid);
 bool wide=width>height;int main_width=wide?142:135,cx=main_width/2;
 bool recording= m->state==STATE_RECORDING;
 bool long_hint=wide && (strchr(m->view.hint,'\n') || strlen(m->view.hint)>24);
 if(!long_hint && !(wide && recording)) screen_draw_icon(c,m->view,m->phase,cx,wide?39:48);
 bool ok=text(c,m->view.title,cx,(long_hint || (wide && recording))?10:wide?81:93,main_width-8,screen_font_measure(SCREEN_FONT_TITLE,m->view.title)>main_width-8?SCREEN_FONT_HINT:SCREEN_FONT_TITLE,C_WHITE);
 const char *hint=m->view.hint;
 if(m->state==STATE_RECORDING) {
  uint16_t color=m->timer.warning==SCREEN_RECORDING_FIVE_SECONDS ? ((m->phase/3)%2?0xF800:C_WHITE) : m->timer.warning==SCREEN_RECORDING_TEN_SECONDS?0xFD20:C_WHITE;
  ok &= text(c,m->timer.text,cx,wide?50:121,main_width-8,SCREEN_FONT_TITLE,color);
  ok &= text(c,m->timer.warning==SCREEN_RECORDING_NORMAL?"ДО КОНЦА":m->timer.warning==SCREEN_RECORDING_TEN_SECONDS?"СКОРО КОНЕЦ":"ЗАВЕРШАЙТЕ",cx,wide?82:148,main_width-8,SCREEN_FONT_HINT,color);
 } else ok &= text(c,hint,cx,long_hint?43:wide?104:123,main_width-8,SCREEN_FONT_HINT,C_MUTED);
 /* Compact indicators are below portrait state, in the right landscape column. */
 int sx=wide?144:0,sy=wide?0:194;
 screen_rect(c,wide?142:8,wide?5:190,wide?1:119,wide?125:1,C_LINE);
 static uint16_t header[135*28];
 memset(header,0,sizeof(header));
 screen_ui_draw_server_icon(header,135,28,18,screen_ui_backend_color(m->backend_status));
 screen_ui_draw_power(header,135,28,m->battery_percent,m->usb,m->charging);
 if(!wide) {
  for(int y=0;y<28;y++) for(int x=0;x<135;x++) if(header[y*135+x]) screen_pixel(c,x,sy+y,header[y*135+x]);
 } else {
  /* Power and server remain recognizable at their native pixel sizes. */
  for(int y=10;y<27;y++) for(int x=9;x<28;x++) if(header[y*135+x]) screen_pixel(c,sx+x-3,y,header[y*135+x]);
  for(int y=10;y<27;y++) for(int x=72;x<135;x++) if(header[y*135+x]) screen_pixel(c,sx+x-45,y+22,header[y*135+x]);
 }
 int wx=wide?215:50,wy=wide?22:218;
 for(int y=-12;y<=-3;y++) for(int x=-12;x<=12;x++) {int r=x*x+y*y;if(y<=-(x<0?-x:x)&&((r>=100&&r<=144)||(r>=25&&r<=49))) screen_pixel(c,wx+x,wy+y,m->wifi?0x07E0:C_MUTED);}
 screen_circle(c,wx,wy-1,1,m->wifi?0x07E0:C_MUTED);
 const char *mode=m->wake_status?(wide?"ГОЛОС +\nКНОПКА":"ГОЛОС + КНОПКА"):m->hold_mode?"УДЕРЖАНИЕ":"НАЖАТИЕ";
 ok &= text(c,mode,wide?192:67,wide?64:223,wide?90:127,SCREEN_FONT_SMALL,C_MUTED);
 if(wide) ok &= text(c,m->device_id && *m->device_id?m->device_id:"ЗАТЕЯ",192,104,90,SCREEN_FONT_SMALL,C_MUTED);
 return ok;
}
