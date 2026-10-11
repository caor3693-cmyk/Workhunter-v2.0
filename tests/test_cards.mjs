import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safePublicURL, opportunityPath } from '../frontend/components/dom.js';
import { fieldFact, cardFacts, resultCard, detailContent, scopeText } from '../frontend/components/cards.js';

const proof = { material_id: 1, source_url: 'https://career.gdut.edu.cn/notice/1', locator: '本公告正文', excerpt: '测试片段，隔离输入', scope: 'partial', observed_at: '2026-10-11T09:00:00+08:00', parser_version: 'isolated-test' };
const known = value => ({ state: 'known', value, evidence: [proof] });
const announcement = { id: 42, title: '隔离公告', school_name: '隔离学校', kind: 'announcement', date_basis: 'publication', source_url: proof.source_url,
  detail_url: '/opportunities/42', work_locations_scope: 'this_announcement', field_observations: {
    published_date: known('2026-09-10'), event_date: { state: 'not_applicable' }, start_time: { state: 'not_applicable' }, end_time: { state: 'not_applicable' }, deadline: { state: 'not_collected' }, event_venue: { state: 'not_applicable' }, work_locations: known(['广州','深圳','珠海','佛山','东莞','惠州']),
  } };

class TextNode {
  constructor(tag) { this.tag = tag; this.attributes = {}; this.children = []; this.ownText = ''; }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent ?? String(child)).join(''); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  set innerHTML(_) { throw new Error('Source HTML must never be inserted'); }
}
function withDOM(run) {
  const original = globalThis.document;
  globalThis.document = { createElement: tag => new TextNode(tag) };
  try { return run(); } finally { globalThis.document = original; }
}
const find = (node, predicate) => [node, ...node.children.flatMap(child => child instanceof TextNode ? find(child, predicate) : [])].filter(predicate);

test('all seven field states have bounded semantics and conflict never leaks a retained raw value', () => {
  for (const [state, text] of Object.entries({ known: '2026-09-10', not_collected: '暂未取得', pending_extraction: '待核实', parse_failed: '待核实', not_disclosed: '原文未披露', not_applicable: null, conflict: '待核实（材料有冲突）' })) {
    const item = { published_date: 'DO-NOT-EXPOSE-RAW', field_observations: { published_date: { state, value: state === 'known' ? '2026-09-10' : null, evidence: [proof, proof] } } };
    assert.equal(fieldFact(item, 'published_date').text, text, state);
    assert.notEqual(fieldFact(item, 'published_date').text, item.published_date);
  }
  assert.equal(fieldFact({ field_observations: { event_venue: { state: 'known', value: '伪已知', evidence: [] } } }, 'event_venue').text, '待核实');
  assert.equal(fieldFact({ event_venue: '只有遗留值，无观察' }, 'event_venue').text, '暂未取得');
});

test('ordinary announcements omit inapplicable venue, label publication date, and limit work locations to five', () => {
  const facts = cardFacts(announcement);
  assert.deepEqual(facts[0], { label: '公告发布时间', text: '2026-09-10' });
  assert.ok(!facts.some(row => row.label === '举办地点'));
  assert.equal(facts.find(row => row.label === '工作地点').text, '广州、深圳、珠海、佛山、东莞 等，详见原文');
  assert.match(cardFacts(announcement, { fullLocations: true }).find(row => row.label === '工作地点').text, /惠州/);
});

test('event time shows only observed times and merges the official cancellation/change status', () => {
  const item = { ...announcement, date_basis: 'event', event_status: 'cancelled', field_observations: { ...announcement.field_observations, event_date: known('2026-10-20'), start_time: { state: 'not_disclosed' }, end_time: { state: 'not_collected' }, event_venue: known('五山校区会议室') } };
  const rows = cardFacts(item);
  assert.equal(rows[0].text, '2026-10-20 · 原文未披露 · 官方已取消');
  assert.ok(!rows[0].text.includes('00:00'));
  assert.equal(rows[1].text, '五山校区会议室');
  assert.equal(cardFacts({ ...item, event_status: 'rescheduled' })[0].text, '2026-10-20 · 原文未披露 · 官方已改期');
});

test('fair locations explicitly remain partial disclosed locations, not every employer location', () => {
  const places = cardFacts({ ...announcement, kind: 'job_fair', work_locations_scope: 'partial_disclosed' }).at(-1);
  assert.equal(places.label, '已披露工作地点');
  assert.match(places.text, /披露不完整/);
});

test('public links reject credentials, unsafe schemes and local IP/name variants', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,test', '/relative', 'https://user:pass@career.gdut.edu.cn/x', 'http://localhost/x', 'http://localhost./x', 'http://box.local./x', 'http://127.0.0.1', 'http://2130706433', 'http://0x7f000001', 'http://10.0.0.1', 'http://172.16.0.1', 'http://192.168.1.1', 'http://169.254.169.254', 'http://[::1]', 'http://[::ffff:127.0.0.1]', 'http://internal']) assert.equal(safePublicURL(value), null, value);
  assert.equal(safePublicURL(proof.source_url), proof.source_url);
});

test('detail paths are precise positive SQLite integers and never external or rounded numbers', () => {
  assert.equal(opportunityPath('9223372036854775807'), '/opportunities/9223372036854775807');
  for (const value of ['0', '-1', '01', '1.2', '9223372036854775808', 9223372036854775807, '42/extra', '1'.repeat(10000)]) assert.equal(opportunityPath(value), null);
});

test('card titles use only matching internal detail links and all source content is literal text', () => withDOM(() => {
  const unsafe = '<img src=x onerror=alert(1)>';
  const card = resultCard({ ...announcement, title: unsafe });
  assert.ok(card.textContent.includes(unsafe));
  const links = find(card, node => node.tag === 'a');
  assert.equal(links[0].attributes.href, '/opportunities/42');
  assert.equal(links[1].attributes.href, proof.source_url);
  assert.equal(links[1].attributes.rel, 'noopener noreferrer');
  assert.equal(find(resultCard({ ...announcement, detail_url: 'javascript:alert(1)' }), node => node.tag === 'a' && node.attributes.href?.startsWith('/')).length, 0);
}));

test('detail keeps full facts, literal fragments, applicable links and readable scope without engineering DOM', () => withDOM(() => {
  const detail = detailContent({ ...announcement, roster_fragments: [{ text: '<script>isolated</script>', scope: 'partial', evidence: [proof] }], job_fragments: [], attachments: [{ label: '隔离附件', url: 'https://career.gdut.edu.cn/file.pdf', scope: 'complete_for_material', evidence: [proof] }], materials: [{ id: 1, source_url: proof.source_url, material_hash: 'a'.repeat(64), fetched_at: '2026-10-11T09:00:00+08:00', scope: 'complete_for_material' }], coverage: { coverage: 'college_supplemental', school_wide: false } });
  assert.match(detail.textContent, /惠州/);
  assert.ok(detail.textContent.includes('<script>isolated</script>'));
  assert.ok(!find(detail, node => node.tag === 'script').length);
  assert.match(detail.textContent, /不能据此判断没有企业或岗位/);
  assert.match(detail.textContent, /非整场或全校完整覆盖/);
  assert.ok(!detail.textContent.includes('a'.repeat(64)));
  assert.ok(!detail.textContent.includes(proof.locator));
  assert.ok(!detail.textContent.includes(proof.parser_version));
  assert.ok(!find(detail, node => ['details', 'summary'].includes(node.tag)).length);
  assert.ok(!find(detail, node => ['material-hash', 'material-record', 'evidence-list'].includes(node.attributes.class)).length);
  assert.match(detail.textContent, /学院补充来源，非全校覆盖/);
  assert.ok(find(detail, node => node.tag === 'a').every(node => safePublicURL(node.attributes.href) || node.attributes.href === '/opportunities/42'));
}));

test('scope absence cannot become an all-school completion claim', () => {
  assert.equal(scopeText(null), '范围待核实');
  assert.equal(scopeText({}), '范围待核实');
  assert.match(scopeText('complete_for_material'), /非整场或全校完整覆盖/);
  assert.equal(scopeText('internal_scope_enum'), '范围待核实');
  assert.equal(scopeText({ type: 'internal_scope_enum', note: 'CSS #technical', page_budget: 400 }), '范围待核实');
  assert.match(scopeText({ type: 'source_list', coverage: 'complete_for_page' }), /栏目列表/);
  assert.match(scopeText({ type: 'source_list', coverage: 'complete_for_page' }), /非全校覆盖/);
});

test('representative detail IDs, missing content and conflicts retain usable safe keyboard links without technical evidence', () => withDOM(() => {
  for (const id of [68, 31, 40]) {
    const detail = detailContent({ ...announcement, id, detail_url: `/opportunities/${id}`, field_observations: { ...announcement.field_observations, deadline: { state: 'conflict', value: 'DO-NOT-EXPOSE-RAW', evidence: [proof] } },
      job_fragments: [{ text: '隔离电气岗位片段', scope: 'this_announcement', evidence: [proof] }], coverage: { coverage: 'internal_scope_enum', school_wide: false }, materials: [{ id: 987654, material_hash: 'INTERNAL-MATERIAL-HASH', parser_version: 'INTERNAL-PARSER' }] });
    assert.match(detail.textContent, /隔离电气岗位片段.*非全校覆盖/);
    assert.match(detail.textContent, /待核实（材料有冲突）/);
    for (const marker of ['DO-NOT-EXPOSE-RAW', 'INTERNAL-MATERIAL-HASH', 'INTERNAL-PARSER', '987654', 'internal_scope_enum', '查看定位证据']) assert.ok(!detail.textContent.includes(marker), marker);
    const links = find(detail, node => node.tag === 'a');
    assert.ok(links.length && links.every(link => safePublicURL(link.attributes.href) && link.attributes.rel === 'noopener noreferrer' && link.attributes.tabindex !== '-1'));
  }
}));

test('unverified optional content is omitted without losing reliable core fields or implying that it does not exist', () => withDOM(() => {
  const detail = detailContent({ ...announcement, official_sources: [null, { url: 'javascript:alert(1)' }], job_fragments: [{ text: 'UNCHECKED-JOB', scope: 'this_announcement', evidence: [] }], attachments: [
    { label: 'UNCHECKED-ATTACHMENT', url: 'https://career.gdut.edu.cn/unverified.pdf', scope: 'this_announcement', evidence: [] },
    { label: 'UNSAFE-ATTACHMENT', url: 'javascript:alert(1)', scope: 'this_announcement', evidence: [proof] },
  ] });
  assert.match(detail.textContent, /2026-09-10/);
  assert.match(detail.textContent, /部分材料仍待核实/);
  assert.match(detail.textContent, /部分附件适用关系待核实/);
  assert.ok(!detail.textContent.includes('UNCHECKED') && !detail.textContent.includes('UNSAFE-ATTACHMENT'));
  assert.ok(!find(detail, node => node.tag === 'a').some(node => node.attributes.href.includes('unverified.pdf')));
}));
