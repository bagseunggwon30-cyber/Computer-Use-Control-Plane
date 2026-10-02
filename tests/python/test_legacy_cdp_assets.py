"""Execute original and ported DOM algorithms against identical captured DOM fixtures.

Node's vm is a test harness for owned fixture objects, not a production dependency
or a security sandbox for untrusted programs. Real browser semantics are tested
separately in test_legacy_cdp_browser.py.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'pcucp-next/python'))
from pcucp_cli.legacy_cdp import _expression
BASELINE_TREE='bf895d3120dd5e145f360cb1c41e1d79a061d048'
HARNESS=r'''
const vm=require('node:vm');const fs=require('node:fs');const rows=JSON.parse(fs.readFileSync(0,'utf8'));
function execute(expression,fixture){
 const events=[];
 function make(data){
   const e={tagName:data.tag||'BUTTON',isConnected:true,isContentEditable:!!data.ce,
     disabled:!!data.disabled,innerText:data.text||'',textContent:data.text||'',value:data.value||'',
     placeholder:(data.attrs||{}).placeholder||'',title:(data.attrs||{}).title||'',id:(data.attrs||{}).id||'',
     attrs:data.attrs||{},labels:[],onclick:data.onclick?function(){}:null,style:data.style||{},
     rect:data.rect||{x:1,y:2,width:50,height:20},focus(){events.push('focus:'+this.id)},
     scrollIntoView(){events.push('scroll:'+this.id)},click(){events.push('click:'+this.id)},
     dispatchEvent(ev){events.push(ev.type+':'+this.id)},getAttribute(a){return this.attrs[a]??null},
     getBoundingClientRect(){return {...this.rect,left:this.rect.x,top:this.rect.y}}};
   if(data.shadow)e.shadowRoot=root(data.shadow);
   if(data.frame)e.contentDocument=root(data.frame);
   return e;
 }
 function root(items){
   const all=items.map(make);
   for(let i=0;i<all.length;i++){
     if(items[i].control!=null){all[i].control=all[items[i].control];all[items[i].control].labels.push(all[i])}
   }
   function matches(el,selector){
     if(selector==='*')return true;
     if(selector[0]==='#')return el.id===selector.slice(1);
     return selector.split(',').some(s=>{
       const m=s.match(/^\[([^=\]]+)(?:=([^\]]+))?\]$/);
       if(m)return m[2]?el.getAttribute(m[1])===m[2].replace(/^['"]|['"]$/g,''):el.getAttribute(m[1])!==null;
       return el.tagName.toLowerCase()===s;
     });
   }
   return {all,querySelectorAll(s){return all.filter(e=>matches(e,s))},querySelector(s){return this.querySelectorAll(s)[0]||null}};
 }
 const document=root(fixture);
 function Input(){};function TextArea(){};
 Object.defineProperty(Input.prototype,'value',{set(v){this.value=v}});
 Object.defineProperty(TextArea.prototype,'value',{set(v){this.value=v}});
 const css={escape(v){return v.replace(/[^a-zA-Z0-9_-]/g,ch=>'\\'+ch)}};
 const window={CSS:css,getComputedStyle(el){return {display:'block',visibility:'visible',opacity:'1',...el.style}}};
 function Event(type,opts){this.type=type;Object.assign(this,opts)}
 const context={document,window,CSS:css,HTMLInputElement:Input,HTMLTextAreaElement:TextArea,Event,InputEvent:Event,KeyboardEvent:Event};
 const result=vm.runInNewContext(expression,context,{timeout:1000});
 return {result,events,values:document.all.map(e=>({id:e.id,value:e.value,text:e.textContent}))};
}
const out=rows.map(row=>({original:execute(row.original,row.fixture),ported:execute(row.ported,row.fixture)}));
process.stdout.write(JSON.stringify(out));
'''


def old_expression(source,asset,args):
    names={'smart':'function _Cdp-RunSmartDomAction','smart_read':'function _Cdp-RunSmartDomAction',
        'type':'function _Action-CdpType','click':'function _Action-CdpClick','deep_read':'function _Action-CdpDeepFind'}
    block=source[source.index(names[asset]):]
    start='$js = @"\n' if asset=='deep_read' else '$expr = @"\n'
    expression=block.split(start,1)[1].split('\n"@',1)[0]
    j=lambda value:json.dumps(value,ensure_ascii=True)
    replacements={'$actionJs':j(args.get('action','click')),'$needleJs':j(args.get('needle','')),
        '$textJs':j(args.get('text','')),'$clearJs':j(args.get('clear',False)),
        '$enterJs':j(args.get('enter',False)),'$planOnlyJs':j(asset=='smart_read'),
        '$clearStr':j(args.get('clear',False)),'$pressEnterStr':j(args.get('enter',False)),
        '`"$selJs`"':j(args.get('selector','')),'"$selJs"':j(args.get('selector','')),'"$textJs"':j(args.get('text','')),
        "'NEEDLE_HERE'":j(args.get('needle',''))}
    for old,new in sorted(replacements.items(),key=lambda pair:-len(pair[0])):expression=expression.replace(old,new)
    return expression


@unittest.skipUnless(shutil.which('node'),'Node fixture evaluator is optional; production needs only Python')
class LegacyCdpAssetParityTests(unittest.TestCase):
    def test_original_and_migrated_algorithms_have_exact_results_and_effects(self):
        source=subprocess.check_output(['git','show',BASELINE_TREE+':scripts/cucp-native-helper.ps1'],cwd=ROOT).decode('utf-8-sig')
        fixture=[dict(tag='BUTTON',text='Save',attrs={'id':'large'},rect=dict(x=2,y=3,width=400,height=500)),
            dict(tag='BUTTON',text='Save',attrs={'id':'small','data-testid':'save','aria-label':'Save'}),
            dict(tag='BUTTON',text='Save',attrs={'id':'disabled'},disabled=True),
            dict(tag='BUTTON',text='Save',attrs={'id':'hidden'},style={'display':'none'}),
            dict(tag='LABEL',text='이름 Name',attrs={'id':'label'},control=5),
            dict(tag='INPUT',text='',attrs={'id':'field','aria-label':'Name','placeholder':'이름'},value='old'),
            dict(tag='DIV',attrs={'id':'host'},shadow=[dict(tag='BUTTON',text='Shadow Save',attrs={'id':'shadow'})]),
            dict(tag='IFRAME',attrs={'id':'frame'},frame=[dict(tag='BUTTON',text='Frame Save',attrs={'id':'framed'})])]
        cases=[]
        for needle in ('Save','Save!','Ｓａｖｅ','sav','missing','이름','Shadow Save','Frame Save'):
            for action in ('click','type'):
                args=dict(needle=needle,action=action,text='',clear=False,enter=False)
                cases.append(dict(original=old_expression(source,'smart_read',args),ported=_expression('smart_read',args),fixture=fixture))
        for asset,args in [('smart',dict(needle='Name',action='type',text='한글😀',clear=True,enter=True)),
                           ('smart',dict(needle='Save',action='click',text='',clear=False,enter=False)),
                           ('type',dict(selector='#field',text='한글😀',clear=True,enter=True)),
                           ('click',dict(selector='#small')),
                           ('deep_read',dict(needle='Save')),('deep_read',dict(needle='이름'))]:
            cases.append(dict(original=old_expression(source,asset,args),ported=_expression(asset,args),fixture=fixture))
        p=subprocess.run(['node','-e',HARNESS],input=json.dumps(cases,ensure_ascii=True),text=True,encoding='utf-8',capture_output=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        actual=json.loads(p.stdout)
        self.assertEqual(len(actual),len(cases))
        for index,value in enumerate(actual):
            with self.subTest(case=index):self.assertEqual(value['ported'],value['original'])


if __name__=='__main__':unittest.main()
