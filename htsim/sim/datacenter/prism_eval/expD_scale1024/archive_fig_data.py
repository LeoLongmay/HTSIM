#!/usr/bin/env python3
"""Compact plotting-data archive for six 1024-scale D1/D3 panels."""
from __future__ import annotations
import argparse,csv,sys
from pathlib import Path
import matplotlib as mpl
mpl.rcParams['pdf.fonttype']=42;mpl.rcParams['ps.fonttype']=42
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent/'common'))
import perf_figs,plot_style
DATA=HERE/'data';ARCHIVE=HERE/'archive_data';FIGS=HERE/'figs';SEEDS=[13,14,15,16,17]
BASE=[('ops','ops'),('reps','reps'),('swift','swift'),('mswift','mswift'),('mnscc','mnscc'),('strack','strack'),('prism','prism')];SETS={'d1':[0,8,16,24,32,40,48],'d3':[10,30,50,70,90]};FILES={'d1':'figD1_failed_sweep.csv','d3':'figD3_load_sweep.csv'};FIELDS=('x','algorithm','goodput_mean_gbps','goodput_std_gbps','avg_fct_mean_us','avg_fct_std_us','p99_fct_mean_us','p99_fct_std_us','n_seeds')
def extract(archive=ARCHIVE):
 archive.mkdir(parents=True,exist_ok=True)
 for key,xs in SETS.items():
  rows=[];prefix='expD1' if key=='d1' else 'expD3load';token='f' if key=='d1' else 'L'
  for arm,_ in BASE:
   a=perf_figs.aggregate(str(DATA),prefix,arm,xs,SEEDS,token)
   if set(a)!=set(xs):raise ValueError(f'incomplete {key}/{arm}')
   for x in xs:
    c=a[x];rows.append({'x':x,'algorithm':arm,'goodput_mean_gbps':repr(c['goodput'][0]),'goodput_std_gbps':repr(c['goodput'][1]),'avg_fct_mean_us':repr(c['avg_fct'][0]),'avg_fct_std_us':repr(c['avg_fct'][1]),'p99_fct_mean_us':repr(c['p99_fct'][0]),'p99_fct_std_us':repr(c['p99_fct'][1]),'n_seeds':5})
  with (archive/FILES[key]).open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator='\n');w.writeheader();w.writerows(rows)
def render(archive=ARCHIVE,figs=FIGS):
 import matplotlib.pyplot as plt
 for key,xs in SETS.items():
  with (archive/FILES[key]).open(newline='',encoding='utf-8') as f:r=csv.DictReader(f);rows=list(r)
  if r.fieldnames!=list(FIELDS) or len(rows)!=len(xs)*7:raise ValueError('invalid archive')
  plot_style.apply_style(24)
  for suffix,ylabel,mk,sk in [('goodput','Goodput (Tbps)','goodput_mean_gbps','goodput_std_gbps'),('avg_fct','Avg FCT (ms)','avg_fct_mean_us','avg_fct_std_us'),('p99_fct','P99 FCT (ms)','p99_fct_mean_us','p99_fct_std_us')]:
   fig,ax=plt.subplots(figsize=(5.2,3.8));scale=1e-3
   for arm,color in BASE:
    s=[next(z for z in rows if z['algorithm']==arm and int(z['x'])==x) for x in xs];ax.errorbar(xs,[float(z[mk])*scale for z in s],yerr=[float(z[sk])*scale for z in s],marker='o',lw=2,ms=6,capsize=3,color=plot_style.COLORS[color])
   ax.set_ylabel(ylabel);ax.set_xlabel('Number of throttled links' if key=='d1' else 'Network load (%)');ax.set_xticks(xs);ax.grid(alpha=.3)
   if suffix=='goodput':ax.yaxis.set_label_coords(-.1,.45)
   if key=='d1':ax.xaxis.label.set_x(.40)
   plt.tight_layout();plot_style.save(fig,('figD1' if key=='d1' else 'figD3_load')+'_'+suffix,str(figs));plt.close(fig)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--extract',action='store_true');p.add_argument('--render',action='store_true');p.add_argument('--archive',type=Path,default=ARCHIVE);p.add_argument('--figs',type=Path,default=FIGS);a=p.parse_args();extract(a.archive) if a.extract else render(a.archive,a.figs) if a.render else p.error('choose --extract or --render')
