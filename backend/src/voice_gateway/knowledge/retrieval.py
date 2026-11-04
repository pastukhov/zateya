"""Bounded read-only Markdown retrieval, deliberately separate from writer pages.

No symlinks are followed: fwalk supplies directory descriptors and leaf opens use
O_NOFOLLOW. Retrieval is lexical evidence selection, never an intent classifier.
"""
from __future__ import annotations

import hashlib
from itertools import islice
import os
import re
import stat
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

import yaml

STOP = set('а и но или в во на о об обо с со к ко у из за по для до от не что как какой какая какие который которых них его ее их это там мы я ты вы он она они же ли бы где когда чем почему сколько лучше известно знаем выбрали решили'.split())
SUFFIXES = sorted(('иями','ями','ами','ого','его','ому','ему','ыми','ими','иях','ах','ях','ов','ев','ий','ый','ой','ая','яя','ое','ее','ые','ие','ую','юю','ом','ем','ам','ям','ией','ия','ию','ии','ью','ь','ы','и','а','я','у','ю','е','о','ский','ская','ские','ского','ской','скими','ская','ться','лись','ли'),key=len,reverse=True)
EXCLUDED = {'attachments','attachment','assets','вложения'}


def terms(text):
    result=[]
    for word in re.findall(r'[^\W_]+',unicodedata.normalize('NFC',text).casefold().replace('ё','е')):
        if word in STOP or len(word)<2:
            continue
        if re.search('[а-я]',word):
            for suffix in SUFFIXES:
                if word.endswith(suffix) and len(word)-len(suffix)>=3:
                    word=word[:-len(suffix)];break
        result.append(word)
    return result


def canonical_link(vault, path):
    return 'obsidian://open?vault='+quote(Path(vault).name,safe='')+'&file='+quote(path.removesuffix('.md'),safe='')


class VaultRetrieval:
    def __init__(self,vault,*,max_files=3000,max_file_bytes=524288,max_total_bytes=8_000_000,
                 max_results=8,max_context_chars=16000,max_scan_seconds=2.0):
        self.vault=Path(vault).resolve()
        self.max_files,self.max_file_bytes,self.max_total_bytes=max_files,max_file_bytes,max_total_bytes
        self.max_results,self.max_context_chars=max_results,max_context_chars
        self.max_scan_seconds=max_scan_seconds

    def search(self,question,prior=None):
        start=time.monotonic(); query=set(terms(question)); old=set(terms((prior or {}).get('question','')))
        prior_paths=set((prior or {}).get('paths',[])[:8]); candidates=[]
        scanned=0;total=0;entries=0;truncated=False;skipped=0;documents={}
        for folder,dirs,files,descriptor in os.fwalk(self.vault,follow_symlinks=False):
            entries+=len(dirs)
            if entries>20000 or time.monotonic()-start>self.max_scan_seconds:
                truncated=True;break
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d.casefold() not in EXCLUDED)
            for name in sorted(files):
                entries+=1
                if scanned>=self.max_files or entries>20000 or total>=self.max_total_bytes or time.monotonic()-start>self.max_scan_seconds:
                    truncated=True;break
                if name.startswith('.') or not name.lower().endswith('.md'):
                    continue
                relative=(Path(folder)/name).relative_to(self.vault).as_posix()
                if len(relative)>512:
                    truncated=True;skipped+=1;continue
                try:
                    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
                    with os.fdopen(fd,'rb') as stream:
                        info=os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode):continue
                        scanned+=1
                        cap=min(self.max_file_bytes,self.max_total_bytes-total)
                        if info.st_size>cap:
                            truncated=True;skipped+=1;continue
                        raw=stream.read(cap+1)
                        total+=len(raw)
                        if len(raw)>cap:truncated=True;continue
                    text=raw.decode('utf-8')
                except (OSError,UnicodeDecodeError):
                    skipped+=1;continue
                title=Path(name).stem;aliases=[]
                if text.startswith('---\n') and '\n---\n' in text[:8192]:
                    try:
                        meta=yaml.safe_load(text[4:].split('\n---\n',1)[0])
                        if isinstance(meta,dict):
                            if isinstance(meta.get('title'),str):title=meta['title'][:200]
                            values=meta.get('aliases',[])
                            if isinstance(values,str):values=[values]
                            if isinstance(values,list):aliases=[a[:200] for a in values[:20] if isinstance(a,str)]
                    except yaml.YAMLError:pass
                else:
                    heading=re.search(r'(?m)^# ([^\n]+)',text)
                    if heading:title=heading[1][:200]
                headline=set(terms(title+' '+Path(name).stem+' '+' '.join(aliases)))
                body=set(terms(text)); direct=12*len(query & headline)+2*len(query & body)
                score=direct+.35*len(old & body)+(2 if relative in prior_paths else 0)
                record=(score,direct,relative,title,text,hashlib.sha256(raw).hexdigest())
                documents[relative]=record
                if score:candidates.append(record)
            if truncated and (scanned>=self.max_files or entries>20000 or total>=self.max_total_bytes or time.monotonic()-start>self.max_scan_seconds):break
        # One-hop topic references only to files already safely scanned. They
        # remain read-only and rank below direct current-question matches.
        included={item[2] for item in candidates};neighbors=0
        for item in sorted(candidates,key=lambda p:(-p[1],p[2]))[:3]:
            if not item[1]:continue
            for match in islice(re.finditer(r"\[\[([^]\n]+)\]\]",item[4]),20):
                target=match[1].split('|',1)[0].split('#',1)[0]
                if not target or Path(target).is_absolute() or '..' in Path(target).parts:continue
                target=target if target.endswith('.md') else target+'.md'
                paths=[target,(Path(item[2]).parent/target).as_posix()]
                selected=next((path for path in paths if path in documents),None)
                if selected is None:
                    matches=[path for path in documents if Path(path).name==Path(target).name]
                    selected=matches[0] if len(matches)==1 else None
                if selected and selected not in included and neighbors<4:
                    record=documents[selected]
                    candidates.append((.5,0,*record[2:]));included.add(selected);neighbors+=1
        pages=[];budget=self.max_context_chars;quote_budget=6000
        for score,direct,path,title,text,sha in sorted(candidates,key=lambda p:(-p[0],p[2])):
            if len(pages)>=self.max_results or budget<=0:
                truncated=True;break
            wanted=query if direct else old
            windows=[(len(wanted & set(terms(text[i:i+1600]))),i,text[i:i+1600]) for i in range(0,len(text),1360)]
            ranked=sorted(windows,key=lambda item:(-item[0],item[1]))
            best=ranked[0][0]
            chosen=sorted([item for item in ranked if item[0]==best][:2 if best else 1],key=lambda item:item[1])
            content='\n…\n'.join(w[2] for w in chosen)[:min(budget,3400)]
            if len(content)<len(text):truncated=True
            snippets=[]
            for section in content.split('\n…\n'):
                for match in re.finditer(r'[^.!?\n]+(?:[.!?]|$)',section):
                    sentence=match[0].strip()
                    for offset in range(0,len(sentence),500):
                        snippet=sentence[offset:offset+500]
                        if snippet:snippets.append((len(wanted & set(terms(snippet))),snippet))
            candidates_quotes=[]
            for _,snippet in sorted(snippets,key=lambda item:-item[0]):
                if len(candidates_quotes)>=4 or quote_budget<len(snippet):break
                if any(item['quote']==snippet for item in candidates_quotes):continue
                ref='q-'+hashlib.sha256((path+'\0'+sha+'\0'+snippet).encode()).hexdigest()[:16]
                candidates_quotes.append(dict(id=ref,quote=snippet));quote_budget-=len(snippet)
            pages.append(dict(path=path,title=title,content=content,sha256=sha,quotes=candidates_quotes,
                              link=canonical_link(self.vault,path),content_truncated=len(content)<len(text)))
            budget-=len(content)
        return {'retrieved_pages':pages,'search':dict(coverage='bounded_local_scan',scanned_files=scanned,
                skipped_files=skipped,truncated=truncated,matched_files=len(candidates),max_files=self.max_files,
                max_file_bytes=self.max_file_bytes,max_total_bytes=self.max_total_bytes,
                max_results=self.max_results,max_context_chars=self.max_context_chars)}
