import test from 'node:test';
import assert from 'node:assert/strict';
import {updatePresentation} from '../frontend/components/updates.js';

test('unknown automatic checks stay unknown while committed manual changes remain visible',()=>{
  const result=updatePresentation({today:{date:'2026-10-12',newly_collected:null,official_changes:null,manual_corrections:2,manual_reverts:1},message:'今日尚未自动检查',categories_overlap:true});
  assert.equal(result.newlyCollected,'—'); assert.equal(result.officialChanges,'—');
  assert.match(result.message,/官方变化 待核实/); assert.match(result.message,/人工纠错 2 条/);
  assert.match(result.message,/撤回更正 1 条/); assert.match(result.message,/不可相加/);
});

test('current collection and historical backfill do not become a sum or a recruitment status claim',()=>{
  const result=updatePresentation({today:{newly_collected:1,current_new:1,historical_backfill:1,undated_new:0},categories_overlap:true});
  assert.equal(result.newlyCollected,1); assert.match(result.message,/当前新收录 1 条/);
  assert.match(result.message,/历史补齐 1 条/); assert.match(result.message,/不可相加/);
});
