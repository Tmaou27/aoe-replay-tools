// Mocked Frida callbacks; this does not test Windows injection.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const mem=Buffer.alloc(0x900000),hooks=new Map(),sent=[];
class P {
 constructor(n){this.n=Number(n)} add(n){return new P(this.n+n)} sub(p){return new P(this.n-p.n)}
 readFloat(){return mem.readFloatLE(this.n)}
 readS32(){return mem.readInt32LE(this.n)} readU8(){return mem.readUInt8(this.n)}
 readS16(){return mem.readInt16LE(this.n)} readU32(){return mem.readUInt32LE(this.n)}
 readPointer(){return new P(this.readU32())} isNull(){return this.n===0}
 equals(p){return this.n===p.n} toString(){return '0x'+this.n.toString(16)} toUInt32(){return this.n>>>0}
 readByteArray(n){return Uint8Array.from(mem.subarray(this.n,this.n+n)).buffer}
}
const base=new P(0x400000),world=new P(0x801000),player=new P(0x803000),attrs=0x804000,esp=new P(0x805000);
const box={ptr:x=>new P(Number(x)),rpc:{exports:{}},Process:{arch:'ia32',pointerSize:4,getModuleByName:()=>({base,path:'fixture.exe'})},
 Interceptor:{attach:(p,c)=>{hooks.set(p.n,c);return {detach(){}}},flush(){}},send:x=>sent.push(...x.records),
 setInterval:()=>1,clearInterval(){}};
vm.createContext(box);vm.runInContext(fs.readFileSync(__dirname+'/agent.js','utf8')+'\nglobalThis.testTargets=targets.concat(resourceTargets,extraTargets,actionTargets);',box);
for(const t of box.testTargets)Buffer.from(t.prefix,'hex').copy(mem,base.n+t.rva);
mem.writeUInt32LE(0x800000,0x7912a0);mem.writeUInt32LE(world.n,0x800424);
mem.writeInt16LE(2,world.n+0x48);mem.writeUInt32LE(player.n,0x802004);mem.writeUInt32LE(0x802000,world.n+0x4c);mem.writeUInt32LE(player.n,0x802000);
mem.writeUInt32LE(198,player.n+0xa4);mem.writeUInt32LE(attrs,player.n+0xa8);
for(let i=0;i<4;i++)mem.writeFloatLE(200,attrs+i*4);
function enter(addr,ecx=player,caller=0x466848){const c={context:{ecx,esp},threadId:1,returnAddress:new P(caller)};hooks.get(addr).onEnter.call(c);return c}
function leave(addr,c){hooks.get(addr).onLeave.call(c,new P(1))}
mem.writeUInt32LE(0x807000,player.n+0x84);mem.writeInt32LE(171,0x80701c);
mem.writeUInt32LE(0x808000,player.n+0x78);mem.writeUInt32LE(1,0x808008);mem.writeUInt32LE(0x808100,0x808004);
mem.writeUInt32LE(0x809000,0x808100);mem.writeInt32LE(2990,0x809004);mem.writeUInt32LE(0x809100,0x809008);
mem.writeUInt32LE(player.n,0x80900c);mem.writeUInt8(2,0x809048);mem.writeUInt8(70,0x809104);mem.writeInt16LE(83,0x809110);mem.writeInt16LE(4,0x809116);
box.rpc.exports.start(1);
const step=enter(0x42d300,world);
mem.writeUInt32LE(player.n,0x80900c);mem.writeUInt32LE(0x809000,0x80a008);mem.writeUInt8(3,0x80a00c);mem.writeInt32LE(100,0x80a018);mem.writeInt32LE(200,0x80a01c);
mem.writeUInt32LE(0x80b000,0x80a034);mem.writeUInt32LE(0x80b100,0x80b008);
mem.writeUInt32LE(0x80c000,0x80b100);mem.writeUInt32LE(0x809000,0x80c008);
mem.writeInt16LE(1,0x80c004);mem.writeUInt8(2,0x80c00c);mem.writeInt32LE(100,0x80c018);
const ga=enter(0x4b3c20,new P(0x80a000));leave(0x4b3c20,ga);
const gb=enter(0x4b3c20,new P(0x80a000));leave(0x4b3c20,gb);
mem.writeInt16LE(70,esp.n+4);mem.writeFloatLE(1,esp.n+8);
let c=enter(0x457e40);mem.writeFloatLE(170,attrs+4);leave(0x457e40,c);
c=enter(0x457ec0);mem.writeFloatLE(200,attrs+4);leave(0x457ec0,c);
mem.writeInt16LE(0,esp.n+4);mem.writeFloatLE(10,esp.n+8);
const ctx=enter(0x45a990,player,0x500123);
c=enter(0x555440,player,0x45ab58);mem.writeFloatLE(210,attrs);leave(0x555440,c);leave(0x45a990,ctx);
mem.writeUInt32LE(player.n,0x80600c);
mem.writeInt16LE(101,esp.n+4);
c=enter(0x402e39,new P(0x806000));mem.writeFloatLE(-290,attrs);leave(0x402e39,c);
c=enter(0x4030df,new P(0x806000));mem.writeFloatLE(210,attrs);leave(0x4030df,c);
mem.writeUInt32LE(100,world.n+0x10);leave(0x42d300,step);
assert.equal(box.rpc.exports.status().active,false);
assert.equal(box.rpc.exports.status().stop_reason,'step_limit');
c=enter(0x555440);leave(0x555440,c);
const stop=box.rpc.exports.stop(),ev=sent.filter(e=>e.kind==='resource_call');
assert.equal(ev.length,17);assert.equal(ev[1].before_bits,Buffer.from(new Float32Array([200]).buffer).toString('hex'));
assert.equal(ev[1].after_bits,Buffer.from(new Float32Array([170]).buffer).toString('hex'));
assert.equal(ev[8].income_context.caller_rva,'0x100123');assert.equal(ev[8].nested_depth,0);
assert.equal(ev[9].argument1_s16,101);assert.equal(ev[9].player_ptr,player.toString());assert.equal(stop.resource_calls,17);assert.equal(stop.resource_pending,0);assert.equal(stop.context_pending,0);assert.equal(stop.errors,0);
assert(ev.every(e=>e.step_id===step.record.id));
console.log('Mock callbacks OK: debit, refund, income context, step association, cleanup.');

const roster=sent.find(e=>e.kind==='roster');assert(roster);assert.equal(roster.players[0].score,171);assert.equal(roster.players[0].objects[0].type_id,83);assert.equal(roster.players[0].objects[0].state,2);assert.equal(roster.step_id,step.record.id);console.log('Roster and score mock OK');

assert.equal(roster.players[0].objects[0].activity.status,'not_decoded');assert(sent.some(e=>e.kind==='template_sample'));console.log('Detailed snapshot schema OK');

const gs=sent.filter(x=>x.kind==='gather_action_sample');assert.equal(gs.length,1);assert.equal(gs[0].unit_id,2990);assert.equal(gs[0].target_id_1,100);assert.equal(gs[0].state_before,3);assert.equal(stop.action_pending,0);console.log('Action sampling and throttling OK');

assert.equal(gs[0].task_tree.nodes_read,2);assert.equal(gs[0].task_tree.root.children[0].task.type_code,1);assert.equal(gs[0].task_tree.truncated,false);console.log('Nested task capture OK');

box.testAction=new P(0x80a000);box.testUnit=new P(0x809000);
mem.writeUInt32LE(0x80b100,0x80b104);
assert.throws(()=>vm.runInContext('taskTree(testAction,testUnit)',box),/cycle/);
mem.writeUInt32LE(0,0x80b104);mem.writeUInt32LE(0,0x80c008);
assert.throws(()=>vm.runInContext('taskTree(testAction,testUnit)',box),/mismatch/);
console.log('Cycle and owner guards OK');
