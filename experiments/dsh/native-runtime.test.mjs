import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createNativeRuntime} from './native-runtime.mjs';
import {createNativeController} from './native-controller.mjs';

test('official Agent Loop executes scoped native tool calls and commits durable Session events',async()=>{
  const root=mkdtempSync(join(tmpdir(),'dsh-native-contract-'));let calls=0;let executed=0;
  const runtime=await createNativeRuntime(root,async(_,options)=>{
    calls++;
    if(calls===2)assert.ok(options.messages.some(m=>m.role==='assistant'&&m.content.some(b=>b.type==='reasoning'&&b.text==='synthetic provider reasoning')));
    return calls===1?{reasoning_content:'synthetic provider reasoning',tool_calls:[{id:'contract-tool-1',function:{name:'business_probe',arguments:'{"value":"owned"}'}}]}:{text:'done'};
  });
  const agent=await runtime.ensure('contract-session','contract-model','Use the scoped business tool.',[{
    name:'business_probe',description:'Contract probe only; no provider request.',
    parameters:{type:'object',properties:{value:{type:'string'}},required:['value'],additionalProperties:false},
    execute:async args=>{assert.equal(args.value,'owned');executed++;return {ok:true};},
  }]);
  await runtime.run(agent,'contract-request','run');
  assert.equal(executed,1);assert.equal(calls,2);
  const records=readFileSync(join(root,'native-events.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  assert.ok(records.some(r=>r.event?.type==='assistant/message'&&r.event.data.message.content.some(b=>b.type==='tool-call')));
  assert.ok(records.some(r=>r.event?.type==='turn/end'&&r.event.data.reason.kind==='completed'));
  assert.equal(records.filter(r=>r.type==='model.request')[0].tools.join(','),'business_probe');
});

test('a failed later turn cannot reuse the previous model answer',async()=>{
  const root=mkdtempSync(join(tmpdir(),'dsh-native-no-stale-'));let calls=0;
  const runtime=await createNativeRuntime(root,async()=>{if(++calls===1)return {text:'first answer'};throw Error('synthetic unknown transport');});
  const agent=await runtime.ensure('no-stale-session','contract-model','Answer normally.',[]);
  await runtime.run(agent,'first','first');assert.equal(runtime.result(agent.id).text,'first answer');
  await assert.rejects(runtime.run(agent,'second','second'),/synthetic unknown transport/);assert.equal(runtime.result(agent.id),undefined);
});

test('a provider failure retains its real code instead of looking like an empty routing decision',async()=>{
  const root=mkdtempSync(join(tmpdir(),'dsh-native-error-code-'));let calls=0;
  const runtime=await createNativeRuntime(root,async()=>{calls++;throw Object.assign(Error('验收调用次数已达上限'),{code:'experiment.budget_exhausted'});});
  const agent=await runtime.ensure('failure-session','contract-model','Answer normally.',[]);
  await assert.rejects(runtime.run(agent,'request','hello'),error=>error.code==='experiment.budget_exhausted'&&error.message==='验收调用次数已达上限');
  assert.equal(calls,1);assert.equal(runtime.result(agent.id),undefined);
});

test('Listing preserves the final validation error when the Executor reaches its call limit', async t => {
  const root = mkdtempSync(join(tmpdir(), 'dsh-listing-limit-'));
  const request = {id:'listing-error', org:'org', user:'user', session:'chat', mode:'auto', text:'策划一张 Listing 主图', asset_ids:[], selection:{}};
  const error = '策划字段不完整：Listing 图的商品事实无法完整关联到购买理由。';
  const ticket = {id:'listing-ticket', assignments:[{id:'a1'}]};
  const core = {
    list: () => [ticket],
    intake: () => ({execute:true, ticket:ticket.id}),
    repo: {tickets:{get:() => ticket}},
    sessionStarted: () => ({session:'native', assignment:'a1'}),
  };
  let executorCalls = 0;
  const response = (value, status=200) => new Response(JSON.stringify(value), {status});
  const toolCall = (id, name, args) => ({tool_calls:[{id, function:{name, arguments:JSON.stringify(args)}}]});
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const input = JSON.parse(init.body);
    if (url.endsWith('/prepare')) return response({skills:[], context:{assets:[]}, conversation:'chat', run:'run',
      catalog:['produce_listing','load_skill','read_context'].map(name=>({name,description:name,parameters:{type:'object'}}))});
    if (url.endsWith('/tool')) return response({error:{code:'dsh.design_invalid', message:error}}, 422);
    if (input.role==='main') return response(toolCall('route', 'route_task', {
      action:'task', executor:'listing', message:'准备策划', ticket:null, plan_only:false, needs_research:false,
    }));
    executorCalls++;
    assert.deepEqual(input.options.tools.map(tool=>tool.name), ['produce_listing']);
    return response(toolCall('design-'+executorCalls, 'produce_listing', {}));
  });
  const controller = await createNativeController(root, core, 'test');
  controller.intake(request);
  let result = controller.status(request);
  for (let i=0; i<200 && result.state!=='failed'; i++) {
    await new Promise(resolve=>setTimeout(resolve, 10));
    result = controller.status(request);
  }
  assert.equal(result.state, 'failed');
  assert.equal(result.error, 'Error: '+error);
  assert.equal(result.error_code, 'dsh.design_invalid');
  assert.equal(result.executor_calls, 2);
  assert.equal(executorCalls, 2);
});
