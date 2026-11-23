'use strict';
const targets = [
  {name:'outer_update_candidate',rva:0x2d300,prefix:'568bf1c786a800000000000000e86ef3'}
];
const resourceTargets=[{"name": "set_attribute_candidate", "rva": 1397632, "prefix": "668b442404566685c00f8ca20000008b"}, {"name": "add_attribute_candidate", "rva": 1397824, "prefix": "56668b7424086685f60f8caf0000008b"}];
const extraTargets=[{"name": "pay_object_cost_candidate", "rva": 360000, "prefix": "8b44240c56578b7c240c8bf16a008b4c"}, {"name": "refund_object_cost_candidate", "rva": 360128, "prefix": "0fbf4424048b51748b04828078044672"}, {"name": "income_context_candidate", "rva": 371088, "prefix": "538b5c240c558b6c240c566683fd0357"}];
extraTargets.push(...[{"name": "pay_research_candidate", "rva": 11833, "prefix": "558bec83ec24894de48b45e48b480c8b", "manager": true}, {"name": "refund_research_candidate", "rva": 12511, "prefix": "558bec83ec1c894dec0fbf450885c07c", "manager": true}]);
let stopReason=null;
let incomeStacks={}, contextPending=0, contextCount=0;
let resourcePending=0, resourceCount=0, resourceRejected=0, resourceDepth={}, playerMap={}, resourceCap=false;
const actionTargets=[{name:'gather_update_candidate',rva:0xb3c20,prefix:'83ec0853568bf15733ff8b461883f8ff'}];
let actionSamples=0,actionLast={},actionPending=0;
let rosterLast=null;
let templateCache={};
let listeners=[], queue=[], timer=null, active=false, sequence=0, callId=0;
let stacks={}, counts={}, idle={}, forceParents=new Set(), errors=0, limit=1000, flushed=0;
function hex(bytes) {return Array.from(new Uint8Array(bytes), x=>x.toString(16).padStart(2,'0')).join('');}
function flush(){if(queue.length){const q=queue;queue=[];send({type:'batch',records:q});flushed+=q.length;}}
function moduleInfo(){const m=Process.getModuleByName('age2_x1.exe');return {m,base:m.base};}
function snapshot(world){
  const n=world.add(0x48).readS16();
  if(n<1 || n>9) throw new Error('player count out of bounds');
  const table=world.add(0x4c).readPointer();
  const players=[];
  for(let slot=0;slot<n;slot++){
    const p=table.add(slot*4).readPointer();
    if(p.isNull()){players.push({slot,null:true});continue;}
    const size=p.add(0xa4).readU32();
    if(size<4 || size>4096) throw new Error('attribute count out of bounds');
    const a=p.add(0xa8).readPointer();
    const bytes=a.readByteArray(16), view=new DataView(bytes);
    const values=Array.from({length:4},(_,i)=>view.getFloat32(i*4,true));
    if(!values.every(Number.isFinite)) throw new Error('non-finite resource');
    const scorePtr=p.add(0x84).readPointer();
    players.push({slot,score:scorePtr.isNull()?null:scorePtr.add(0x1c).readS32(),player_ptr:p.toString(),resource_bits_hex:hex(bytes),
      food:values[0],wood:values[1],stone:values[2],gold:values[3]});
  }
  return {world:world.toString(),time_ms:world.add(0x10).readU32(),
    previous_time_candidate:world.add(0x14).readU32(),
    step_delta_candidate:world.add(0x18).readU32(),players};
}
function roster(s){
  const players=[];
  for(const p of s.players){
    if(p.slot===0 || !p.player_ptr)continue;
    const player=ptr(p.player_ptr), list=player.add(0x78).readPointer();
    const objects=[], seen=new Set();
    if(list.isNull())throw new Error('Null object list for '+p.slot);
    const n=list.add(8).readU32(), array=list.add(4).readPointer();
    if(n>20000)throw new Error('Object list bound exceeded');
    for(let i=0;i<n;i++){
      const o=array.add(i*4).readPointer();if(o.isNull())continue;
      const master=o.add(8).readPointer();if(master.isNull())throw new Error('Null master');
      const id=o.add(4).readS32();if(seen.has(id))throw new Error('Duplicate object ID');seen.add(id);
      objects.push({id,type_id:master.add(0x10).readS16(),struct_type:master.add(4).readU8(),
        class_id:master.add(0x16).readS16(),state:o.add(0x48).readU8(),
        owner_ptr:o.add(0xc).readPointer().toString(),
        hp:o.add(0x30).readFloat(),x:o.add(0x38).readFloat(),y:o.add(0x3c).readFloat(),
        z:o.add(0x40).readFloat(),resource_amount_candidate:o.add(0x44).readFloat(),
        resource_type_candidate:o.add(0x4c).readS16(),container_id_candidate:o.add(0x78).readS32(),
        max_hp_candidate:master.add(0x2a).readS16(),template_pointer:master.toString(),
        activity:{status:'not_decoded'},combat_upgrades:{status:'not_decoded'}});
      const key=master.toString(), raw=hex(master.readByteArray(0x80));
      if(templateCache[key]!==raw){templateCache[key]=raw;queue.push({kind:'template_sample',sequence:++sequence,
        time_ms:s.time_ms,slot:p.slot,pointer:key,raw_prefix_hex:raw});}
    }
    players.push({slot:p.slot,player_ptr:p.player_ptr,score:p.score,objects});
  }
  const all=players.flatMap(p=>p.objects.map(o=>({...o,slot:p.slot})));
  const byId=new Map(all.map(o=>[o.id,o]));
  const centers=all.filter(o=>o.type_id===109 && o.state===2);
  for(const p of players)for(const o of p.objects){
    const host=byId.get(o.container_id_candidate);
    o.container_candidate=host?{id:host.id,type_id:host.type_id,slot:host.slot}:null;
    // No claim that a negative/unresolved link proves the unit is outside.
    o.nearest_own_tc_candidate=null;
    if(o.container_id_candidate===-1 && Number.isFinite(o.x) && Number.isFinite(o.y)){
      let best=null;
      for(const tc of centers){if(tc.slot!==p.slot)continue;
        const d=Math.hypot(o.x-tc.x,o.y-tc.y);
        if(best===null || d<best.distance_tiles)best={id:tc.id,type_id:tc.type_id,distance_tiles:d};
      }
      o.nearest_own_tc_candidate=best;
    }
  }
  return {kind:'roster',time_ms:s.time_ms,sequence:++sequence,players,
    scope:'player_list_0x78; completeness_for_garrison_and_dead_objects_unvalidated'};
}
function taskTree(action,unit){
  const seenActions=new Set(),seenNodes=new Set();let total=0,truncated=false;
  function visit(a,depth){
    const key=a.toString();
    if(seenActions.has(key))throw new Error('Repeated task pointer');
    if(depth>=4 || total>=32){truncated=true;return null;}
    seenActions.add(key);total++;
    if(!a.add(8).readPointer().equals(unit))throw new Error('Task unit mismatch');
    const result={pointer:key,type_code:a.add(4).readS16(),state_code:a.add(0xc).readU8(),
      target_id_1:a.add(0x18).readS32(),target_id_2:a.add(0x1c).readS32(),
      destination:[a.add(0x20).readFloat(),a.add(0x24).readFloat(),a.add(0x28).readFloat()],children:[]};
    const list=a.add(0x34).readPointer();
    if(list.isNull())return result;
    let node=list.add(8).readPointer(),count=0;
    while(!node.isNull()){
      if(count>=8 || total>=32){truncated=true;break;}
      if(seenNodes.has(node.toString()))throw new Error('Task list cycle');
      seenNodes.add(node.toString());
      const child=node.readPointer();
      if(child.isNull())throw new Error('Null task in list');
      result.children.push({list_index:count,task:visit(child,depth+1)});
      count++;node=node.add(4).readPointer();
    }
    return result;
  }
  const root=visit(action,0);return {root,truncated,nodes_read:total};
}
function failure(e){errors++;queue.push({kind:'error',sequence:++sequence,error:String(e)});if(errors>=3)active=false;}
rpc.exports={
  status(){return {active,stop_reason:stopReason};},
  inspect(){
    const {m}=moduleInfo();
    return {path:m.path,base:m.base.toString(),arch:Process.arch,pointer_size:Process.pointerSize,
      targets:targets.concat(resourceTargets,extraTargets,actionTargets).map(t=>({...t,loaded_prefix:hex(m.base.add(t.rva).readByteArray(16))}))};
  },
  start(maxCalls){
    if(listeners.length)throw new Error('Already attached');
    if(Process.arch!=='ia32'||Process.pointerSize!==4)throw new Error('Expected x86 process');
    limit=maxCalls;
    const {base}=moduleInfo();
    // Verify ALL prologues before any hook is installed.
    for(const t of targets.concat(resourceTargets,extraTargets,actionTargets))if(hex(base.add(t.rva).readByteArray(16))!==t.prefix)throw new Error('Prologue mismatch: '+t.name);
    try{
      for(const t of targets){
        counts[t.name]=0;idle[t.name]=0;
        listeners.push(Interceptor.attach(base.add(t.rva),{
          onEnter(){
            this.traced=false;
            if(!active || counts[t.name]>=limit)return;
            try{
              const root=base.add(0x3912a0).readPointer();
              const world=root.add(0x424).readPointer();
              if(!this.context.ecx.equals(world))return;
              const tid=this.threadId, stack=stacks[tid] || (stacks[tid]=[]);
              this.record={kind:'call',id:++callId,name:t.name,thread_id:tid,
                parent_id:stack.length?stack[stack.length-1]:null,
                enter_sequence:++sequence,before:snapshot(world)};
              this.world=world;this.tid=tid;stack.push(this.record.id);
              playerMap={};for(const p of this.record.before.players)if(p.player_ptr)playerMap[p.player_ptr]=p.slot;
              this.traced=true;
            }catch(e){failure(e);}
          },
          onLeave(retval){
            if(!this.traced)return;
            try{
              const r=this.record;r.after=snapshot(this.world);
              if(rosterLast===null || r.after.time_ms<rosterLast || r.after.time_ms-rosterLast>=1000){
                const census=roster(r.after);census.step_id=r.id;queue.push(census);
                rosterLast=r.after.time_ms;forceParents.add(r.id);
              }
              r.return_al=retval.toUInt32() & 255;r.leave_sequence=++sequence;
              const changed = r.before.time_ms!==r.after.time_ms ||
                JSON.stringify(r.before.players)!==JSON.stringify(r.after.players);
              const forced=forceParents.delete(r.id);
              if(changed || forced || idle[t.name]<3){
                r.retention_reason=changed?'changed':forced?'child_changed':'initial_idle';
                queue.push(r);counts[t.name]++;
                if(counts[t.name]>=limit){stopReason="step_limit";active=false;}
                if(r.parent_id!==null)forceParents.add(r.parent_id);
              }
              if(!changed)idle[t.name]++;
            }catch(e){failure(e);}
            finally{
              const s=stacks[this.tid];
              if(!s || s.pop()!==this.record.id)failure('Unbalanced call stack');
            }
          }
        }));
      }
      for(const t of resourceTargets){
        listeners.push(Interceptor.attach(base.add(t.rva),{
          onEnter(){
            this.capture=false;
            if(!active)return;
            try{
              const index=this.context.esp.add(4).readS16();
              if(index<0 || index>3)return;
              if(resourceCount>=1000000){resourceCap=true;stopReason="resource_limit";active=false;return;}
              const player=t.manager?this.context.ecx.add(0xc).readPointer():this.context.ecx, slot=playerMap[player.toString()];
              if(slot===undefined){resourceRejected++;return;}
              const ptr=player.add(0xa8).readPointer().add(index*4);
              const stack=stacks[this.threadId] || [];
              const depth=resourceDepth[this.threadId] || 0;
              this.event={kind:'resource_call',name:t.name,id:++callId,
                step_id:stack.length?stack[stack.length-1]:null,thread_id:this.threadId,
                slot,player_ptr:player.toString(),resource_index:index,nested_depth:depth,
                caller:this.returnAddress.toString(),caller_rva:this.returnAddress.sub(base).toString(),
                enter_sequence:++sequence,before_bits:hex(ptr.readByteArray(4)),
                argument_bits:hex(this.context.esp.add(8).readByteArray(4)),
                income_context:(incomeStacks[this.threadId] || []).slice(-1)[0] || null};
              this.ptr=ptr;this.tid=this.threadId;this.capture=true;
              resourceDepth[this.tid]=depth+1;resourcePending++;resourceCount++;
              if(this.event.step_id!==null)forceParents.add(this.event.step_id);
            }catch(e){failure(e);}
          },
          onLeave(){
            if(!this.capture)return;
            try{this.event.after_bits=hex(this.ptr.readByteArray(4));this.event.leave_sequence=++sequence;queue.push(this.event);}
            catch(e){failure(e);}
            finally{resourcePending--;resourceDepth[this.tid]--;}
          }
        }));
      }
      for(const t of extraTargets){
        const contextOnly=t.name==='income_context_candidate';
        listeners.push(Interceptor.attach(base.add(t.rva),{
          onEnter(){
            this.capture=false;
            if(!active)return;
            try{
              const player=t.manager?this.context.ecx.add(0xc).readPointer():this.context.ecx, slot=playerMap[player.toString()];
              if(slot===undefined){resourceRejected++;return;}
              const tid=this.threadId, esp=this.context.esp;
              const info={name:t.name,slot,player_ptr:player.toString(),
                caller:this.returnAddress.toString(),caller_rva:this.returnAddress.sub(base).toString(),
                argument1_s16:esp.add(4).readS16(),argument2_bits:t.manager?null:hex(esp.add(8).readByteArray(4))};
              if(contextOnly){
                const ctxs=incomeStacks[tid] || (incomeStacks[tid]=[]);
                ctxs.push(info);contextPending++;contextCount++;
                this.tid=tid;this.capture=true;return;
              }
              if(resourceCount+4>1000000){resourceCap=true;stopReason="resource_limit";active=false;return;}
              const ptr=player.add(0xa8).readPointer();
              const stack=stacks[tid] || [], depth=resourceDepth[tid] || 0;
              this.events=Array.from({length:4},(_,i)=>({kind:'resource_call',...info,id:++callId,
                step_id:stack.length?stack[stack.length-1]:null,thread_id:tid,
                resource_index:i,nested_depth:depth,enter_sequence:++sequence,
                before_bits:hex(ptr.add(i*4).readByteArray(4))}));
              this.ptr=ptr;this.tid=tid;this.capture=true;
              resourceDepth[tid]=depth+1;resourcePending++;resourceCount+=4;
              if(stack.length)forceParents.add(stack[stack.length-1]);
            }catch(e){failure(e);}
          },
          onLeave(retval){
            if(!this.capture)return;
            if(contextOnly){incomeStacks[this.tid].pop();contextPending--;return;}
            try{
              for(const e of this.events){
                e.after_bits=hex(this.ptr.add(e.resource_index*4).readByteArray(4));
                e.return_al=retval.toUInt32()&255;e.leave_sequence=++sequence;queue.push(e);
              }
            }catch(e){failure(e);}
            finally{resourceDepth[this.tid]--;resourcePending--;}
          }
        }));
      }
      for(const t of actionTargets){
        listeners.push(Interceptor.attach(base.add(t.rva),{
          onEnter(){
            this.capture=false;if(!active)return;
            try{
              const action=this.context.ecx, unit=action.add(8).readPointer();
              const player=unit.add(0xc).readPointer(),slot=playerMap[player.toString()];
              if(slot===undefined || slot===0)return;
              const world=base.add(0x3912a0).readPointer().add(0x424).readPointer();
              const time=world.add(0x10).readU32(), id=unit.add(4).readS32();
              const state=action.add(0xc).readU8(),target1=action.add(0x18).readS32(),target2=action.add(0x1c).readS32();
              const tree=taskTree(action,unit);
              const key=slot+':'+id, sig=state+':'+target1+':'+target2+':'+JSON.stringify(tree,(k,v)=>k==='destination'||k==='pointer'?undefined:v),old=actionLast[key];
              if(old && old.sig===sig && time>=old.time && time-old.time<1000)return;
              if(actionSamples>=5000000){stopReason='action_limit';active=false;return;}
              const stack=stacks[this.threadId] || [];
              this.action=action;this.record={kind:'gather_action_sample',time_ms:time,slot,unit_id:id,
                task_tree:tree,action_pointer:action.toString(),state_before:state,target_id_1:target1,target_id_2:target2,
                raw_before_hex:hex(action.readByteArray(0x40)),
                step_id:stack.length?stack[stack.length-1]:null,enter_sequence:++sequence};
              this.capture=true;actionPending++;actionSamples++;actionLast[key]={sig,time};
              if(stack.length)forceParents.add(stack[stack.length-1]);
            }catch(e){failure(e);}
          },
          onLeave(){
            if(!this.capture)return;
            // Do not dereference the action on return: it could have been replaced/freed.
            this.record.leave_sequence=++sequence;queue.push(this.record);actionPending--;
          }
        }));
      }
      Interceptor.flush();active=true;timer=setInterval(flush,200);
      return {started:true,limit_per_function:limit};
    }catch(e){for(const l of listeners)l.detach();listeners=[];throw e;}
  },
  stop(){
    active=false;
    const pending=Object.values(stacks).reduce((n,s)=>n+s.length,0);
    for(const l of listeners)l.detach();listeners=[];
    Interceptor.flush();if(timer!==null){clearInterval(timer);timer=null;}flush();
    return {action_samples:actionSamples,action_pending:actionPending,stop_reason:stopReason,context_pending:contextPending,context_calls:contextCount,resource_calls:resourceCount,resource_pending:resourcePending,resource_rejected:resourceRejected,resource_cap:resourceCap,counts,idle_calls_seen:idle,errors,pending_calls_at_stop:pending,records_sent:flushed,
      capped:Object.values(counts).some(n=>n>=limit)};
  }
};
