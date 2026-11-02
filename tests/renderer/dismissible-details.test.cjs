const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mkdtempSync, mkdirSync, rmSync} = require('node:fs');
const {dirname, join, resolve} = require('node:path');
const {execFileSync} = require('node:child_process');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, {recursive:true});
const output = mkdtempSync(join(temp, 'details-dismiss-'));
process.on('exit', () => {assert.equal(dirname(output),temp);rmSync(output,{recursive:true,force:true});});
const compilerPackage = require.resolve('typescript/package.json',{paths:[root]});
execFileSync(process.execPath,[resolve(dirname(compilerPackage),require(compilerPackage).bin.tsc),'--ignoreConfig',
  '--strict','--target','ES2022','--module','commonjs','--skipLibCheck','--outDir',output,
  'desktop/renderer/src/dismissibleDetails.ts'],{cwd:root,stdio:'inherit'});
const {installDetailsDismissal} = require(join(output,'dismissibleDetails.js'));

function fixture() {
  const menus=[], focused=[], listeners=new Map();
  const document={
    querySelectorAll:()=>menus.filter(menu=>menu.marked && menu.open),
    addEventListener(name, listener, capture=false) {
      const key=`${name}:${capture}`;
      if(!listeners.has(key))listeners.set(key,new Set());
      listeners.get(key).add(listener);
    },
    removeEventListener(name,listener,capture=false){listeners.get(`${name}:${capture}`)?.delete(listener);},
  };
  return {menus,focused,listeners,document,
    menu(marked=true) {
      const summary={focus:options=>focused.push(options)},action={};
      const menu={marked,open:true,summary,action,querySelector:()=>summary,querySelectorAll:()=>[action]};
      menus.push(menu);return menu;
    },
    dispatch(type,path,changes={}) {
      const event={key:'Escape',defaultPrevented:false,isComposing:false,prevented:0,stopped:0,
        composedPath:()=>path,preventDefault(){this.prevented++;},stopPropagation(){this.stopped++;},...changes};
      for(const capture of [true,false])for(const listener of listeners.get(`${type}:${capture}`)||[])listener(event);
      return event;
    },
  };
}

test('outside pointers dismiss transient menus without cancelling the clicked action or taking focus',()=>{
  const f=fixture(),menu=f.menu(),record=f.menu(false),cleanup=installDetailsDismissal(f.document);
  const event=f.dispatch('pointerdown',[{name:'outside button'}]);
  assert.equal(menu.open,false);assert.equal(record.open,true);
  assert.equal(event.prevented,0);assert.equal(event.stopped,0);assert.deepEqual(f.focused,[]);
  cleanup();
});

test('inside input, select, summary and shadow paths keep their menu while dismissing another one',()=>{
  const f=fixture(),first=f.menu(),second=f.menu(),cleanup=installDetailsDismissal(f.document);
  for(const child of [first.summary,{name:'input'},{name:'native select'},{name:'shadow child'}]) {
    first.open=second.open=true;
    f.dispatch('pointerdown',[child,first]);
    assert.equal(first.open,true);assert.equal(second.open,false);
  }
  cleanup();
});

test('keyboard focus can move within a menu and closes it when it leaves without stealing focus',()=>{
  const f=fixture(),menu=f.menu(),cleanup=installDetailsDismissal(f.document);
  f.dispatch('focusin',[{},menu]);assert.equal(menu.open,true);
  const event=f.dispatch('focusin',[{}]);assert.equal(menu.open,false);
  assert.equal(event.prevented,0);assert.deepEqual(f.focused,[]);cleanup();
});

test('Escape closes only the nearest open menu and restores its trigger focus',()=>{
  const f=fixture(),outer=f.menu(),inner=f.menu(),cleanup=installDetailsDismissal(f.document);
  const event=f.dispatch('keydown',[{},inner,outer]);
  assert.equal(inner.open,false);assert.equal(outer.open,true);
  assert.equal(event.prevented,1);assert.equal(event.stopped,1);
  assert.deepEqual(f.focused,[{preventScroll:true}]);cleanup();
});

test('handled Escape, composition, other keys and modal focus do not dismiss a different menu',()=>{
  const f=fixture(),menu=f.menu(),cleanup=installDetailsDismissal(f.document);
  for(const changes of [{defaultPrevented:true},{isComposing:true},{key:'Enter'},{key:'Tab'}]) {
    const event=f.dispatch('keydown',[menu],changes);
    assert.equal(menu.open,true);assert.equal(event.prevented,0);
  }
  const modalEscape=f.dispatch('keydown',[{name:'modal'}]);
  assert.equal(menu.open,true);assert.equal(modalEscape.prevented,0);cleanup();
});

test('marked menu actions dismiss before their callback while ordinary internal controls stay open',()=>{
  const f=fixture(),menu=f.menu(),cleanup=installDetailsDismissal(f.document),calls=[];
  const input=f.dispatch('click',[{},menu]);assert.equal(menu.open,true);assert.equal(input.prevented,0);
  const event=f.dispatch('click',[{},menu.action,menu]);
  assert.equal(menu.open,false);if(!event.prevented)calls.push('original action');
  assert.deepEqual(calls,['original action']);assert.deepEqual(f.focused,[]);cleanup();
});

test('delegation handles menus inserted after installation and cleanup leaves no duplicate listeners',()=>{
  const f=fixture(),cleanup=installDetailsDismissal(f.document),menu=f.menu();
  f.dispatch('pointerdown',[{}]);assert.equal(menu.open,false);
  cleanup();for(const listeners of f.listeners.values())assert.equal(listeners.size,0);
  const cleanupAgain=installDetailsDismissal(f.document);
  for(const listeners of f.listeners.values())assert.equal(listeners.size,1);
  menu.open=true;cleanupAgain();f.dispatch('pointerdown',[{}]);assert.equal(menu.open,true);
});
