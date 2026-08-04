#!/usr/bin/env python3
"""Compact plotting-data archive for the six permutation performance panels."""
from __future__ import annotations
import argparse,csv,sys
from pathlib import Path
import matplotlib as mpl
mpl.rcParams['pdf.fonttype']=42; mpl.rcParams['ps.fonttype']=42
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE.parent/'common'))
import perf_figs,plot_style
DATA=HERE/'data'; ARCHIVE=HERE/'archive_data'; FIGS=HERE/'figs'; SEEDS=[13,14,15,16,17]
BASE=[('ops','ops'),('reps','reps'),('swift','swift'),('mswift','mswift'),('mnscc','mnscc'),('strack','strack'),('prism','prism')]
SETS={'p128':[0,2,4,6,8,10,12],'p1024':[0,8,16,24,32,40,48]}; FILES={'p128':'figE_p128_sweep.csv','p1024':'figE_p1024_sweep.csv'}
FIELDS=('failed','algorithm','goodput_mean_gbps','goodput_std_gbps','avg_fct_mean_us','avg_fct_std_us','p99_fct_mean_us','p99_fct_std_us','n_seeds')
def extract(archive=ARCHIVE):
 archive.mkdir(parents=True,exist_ok=True)
 for key,xs in SETS.items():
  rows=[]
  for arm,_ in BASE:
   a=perf_figs.aggregate(str(DATA),f'expE{key}',arm,xs,SEEDS)
   if set(a)!=set(xs): raise ValueError(f'incomplete {key}/{arm}')
   for x in xs:
    c=a[x]; rows.append({'failed':x,'algorithm':arm,'goodput_mean_gbps':repr(c['goodput'][0]),'goodput_std_gbps':repr(c['goodput'][1]),'avg_fct_mean_us':repr(c['avg_fct'][0]),'avg_fct_std_us':repr(c['avg_fct'][1]),'p99_fct_mean_us':repr(c['p99_fct'][0]),'p99_fct_std_us':repr(c['p99_fct'][1]),'n_seeds':5})
  with (archive/FILES[key]).open('w',newline='',encoding='utf-8') as f:
   w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator='\n');w.writeheader();w.writerows(rows)
def render(archive=ARCHIVE,figs=FIGS):
 import matplotlib.pyplot as plt
 for key,xs in SETS.items():
  with (archive/FILES[key]).open(newline='',encoding='utf-8') as f:
   r=csv.DictReader(f); rows=list(r)
  if r.fieldnames!=list(FIELDS) or len(rows)!=49: raise ValueError('invalid archive')
  plot_style.apply_style(24)
  for suffix,ylabel,mk,sk,scale in [('goodput','Goodput (Tbps)','goodput_mean_gbps','goodput_std_gbps',1e-3),('avg_fct','Avg FCT (ms)','avg_fct_mean_us','avg_fct_std_us',1e-3),('p99_fct','P99 FCT (ms)','p99_fct_mean_us','p99_fct_std_us',1e-3)]:
   fig,ax=plt.subplots(figsize=(5.2,3.8))
   for arm,color in BASE:
    s=[next(z for z in rows if z['algorithm']==arm and int(z['failed'])==x) for x in xs];ax.errorbar(xs,[float(z[mk])*scale for z in s],yerr=[float(z[sk])*scale for z in s],marker='o',lw=2,ms=6,capsize=3,color=plot_style.COLORS[color])
   ax.set_ylabel(ylabel);ax.set_xlabel('Number of throttled links');ax.set_xticks(xs);ax.grid(alpha=.3)
   ax.xaxis.label.set_x(.39 if (key=='p128' and suffix in ('avg_fct','goodput')) or (key=='p1024' and suffix=='avg_fct') else .40)
   if suffix=='goodput': ax.yaxis.set_label_coords(-.23 if key=='p128' else -.16,.45)
   plt.tight_layout();plot_style.save(fig,f'figE_{key}_{suffix}',str(figs));plt.close(fig)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--extract',action='store_true');p.add_argument('--render',action='store_true');p.add_argument('--archive',type=Path,default=ARCHIVE);p.add_argument('--figs',type=Path,default=FIGS);a=p.parse_args();extract(a.archive) if a.extract else render(a.archive,a.figs) if a.render else p.error('choose --extract or --render')
