import { element, opportunityPath, safePublicURL } from './dom.js';

export const FIELD_LABELS = { published_date: '公告发布时间', event_date: '活动日期', start_time: '开始时刻', end_time: '结束时刻', deadline: '投递截止', event_venue: '举办地点', work_locations: '工作地点' };
const UNKNOWN = { not_collected: '暂未取得', pending_extraction: '待核实', parse_failed: '待核实', not_disclosed: '原文未披露', conflict: '待核实（材料有冲突）' };
const KINDS = { campus_talk: '线下宣讲会', job_fair: '双选会 / 招聘会', online_recruitment: '线上招聘', announcement: '招聘公告' };
const SCOPES = { partial: '部分材料', complete_for_material: '本份材料已完整读取，非整场或全校完整覆盖', unknown: '范围待核实', this_announcement: '本公告', disclosed_employers: '本公告已披露企业', partial_disclosed: '本公告部分披露', college_supplemental: '学院补充来源，非全校覆盖' };

export function fieldFact(item, field) {
  const observation = item.field_observations?.[field];
  const state = observation?.state || 'not_collected';
  if (state === 'not_applicable') return { state, text: null, value: null };
  const evidence = observation?.evidence;
  const value = observation?.value;
  const validValue = field === 'work_locations' ? Array.isArray(value) && value.length > 0 && value.every(place => typeof place === 'string' && place.trim()) : typeof value === 'string' && value.trim();
  const validEvidence = Array.isArray(evidence) && evidence.length > 0 && evidence.every(proof => safePublicURL(proof.source_url) && proof.locator && proof.excerpt && proof.scope);
  if (state !== 'known' || !validValue || !validEvidence) return { state: state === 'known' ? 'pending_extraction' : state, text: UNKNOWN[state] || '待核实', value: null };
  return { state: 'known', text: Array.isArray(value) ? value.join('、') : value, value };
}

export function cardFacts(item, { fullLocations = false } = {}) {
  const rows = [];
  if (item.date_basis === 'event') {
    const date = fieldFact(item, 'event_date');
    const start = fieldFact(item, 'start_time');
    const end = fieldFact(item, 'end_time');
    const time = start.state === 'known' ? start.text + (end.state === 'known' ? `—${end.text}` : '') : start.text;
    const status = { cancelled: '官方已取消', rescheduled: '官方已改期' }[item.event_status];
    rows.push({ label: '活动时间', text: [date.text, time, status].filter(Boolean).join(' · ') || '暂未取得' });
  } else {
    const published = fieldFact(item, 'published_date');
    if (published.text !== null) rows.push({ label: FIELD_LABELS.published_date, text: published.text });
  }
  const venue = fieldFact(item, 'event_venue');
  if (venue.text !== null) rows.push({ label: FIELD_LABELS.event_venue, text: venue.text });
  const places = fieldFact(item, 'work_locations');
  if (places.text !== null) {
    const aggregate = item.kind === 'job_fair' || item.work_locations_scope !== 'this_announcement';
    const text = places.value ? places.value.slice(0, fullLocations ? undefined : 5).join('、') + (!fullLocations && places.value.length > 5 ? ' 等，详见原文' : '') : places.text;
    rows.push({ label: aggregate ? '已披露工作地点' : FIELD_LABELS.work_locations, text: text + (item.work_locations_scope === 'partial_disclosed' ? '（披露不完整）' : '') });
  }
  const deadline = fieldFact(item, 'deadline');
  if (deadline.state === 'known' || deadline.state === 'conflict') rows.push({ label: FIELD_LABELS.deadline, text: deadline.text });
  return rows;
}

export function factList(rows) {
  return element('dl', { className: 'fact-list' }, rows.flatMap(row => [element('dt', { text: row.label }), element('dd', { text: row.text })]));
}

export function officialLink(url, label = '官方原文 ↗') {
  const safe = safePublicURL(url);
  return safe ? element('a', { className: 'original-link', href: safe, target: '_blank', rel: 'noopener noreferrer', text: label }) : element('span', { className: 'source-message', text: '官方链接待核实' });
}

export function resultCard(item) {
  const heading = element('h3');
  const path = opportunityPath(item.id);
  // Only the server's matching in-site detail URL can become a title link.
  if (path && item.detail_url === path) heading.append(element('a', { href: path, text: item.title || '标题尚未取得' }));
  else heading.textContent = item.title || '标题尚未取得';
  return element('article', { className: 'opportunity-card' }, [
    element('p', { className: 'card-school', text: [item.school_name || '学校归属待核实', KINDS[item.kind] || '类型待核实', item.campus_name].filter(Boolean).join(' · ') }),
    heading, factList(cardFacts(item)), officialLink(item.source_url),
  ]);
}

export function scopeText(scope) {
  if (typeof scope === 'string') return SCOPES[scope] || scope;
  if (!scope || typeof scope !== 'object') return '范围待核实';
  const parts = [];
  for (const key of ['completeness', 'coverage', 'type', 'kind', 'scope', 'note', 'description']) {
    if (typeof scope[key] === 'string') parts.push(SCOPES[scope[key]] || scope[key]);
  }
  if (scope.school_wide === false) parts.push('非全校覆盖');
  if (scope.page_budget) parts.push(`最多检查 ${scope.page_budget} 页`);
  if (scope.window && typeof scope.window === 'object') parts.push([scope.window.from, scope.window.to].filter(Boolean).join(' 至 '));
  return parts.filter(Boolean).join(' · ') || '范围待核实';
}

function evidenceList(evidence = []) {
  const valid = Array.isArray(evidence) ? evidence : [];
  return element('ul', { className: 'evidence-list' }, valid.map(proof => element('li', {}, [
    element('p', { text: `${proof.locator || '定位待核实'} · ${scopeText(proof.scope)}` }),
    element('blockquote', { text: proof.excerpt || '尚未取得可展示片段' }),
    officialLink(proof.source_url, '核对这份原文 ↗'),
  ])));
}

export function detailContent(item) {
  const content = element('div', { className: 'announcement-detail' }, [resultCard(item)]);
  const facts = element('section', { className: 'detail-section' }, [element('h2', { text: '本公告事实与依据' })]);
  for (const [field, label] of Object.entries(FIELD_LABELS)) {
    const fact = fieldFact(item, field);
    if (fact.text === null) continue;
    const row = element('div', { className: 'field-evidence' }, [element('h3', { text: label }), element('p', { text: fact.text })]);
    const evidence = item.field_observations?.[field]?.evidence;
    if (Array.isArray(evidence) && evidence.length) row.append(element('details', {}, [element('summary', { text: '查看定位证据' }), evidenceList(evidence)]));
    facts.append(row);
  }
  content.append(facts);
  if (item.official_sources?.length) content.append(element('section', { className: 'detail-section' }, [element('h2', { text: '官方来源' }), ...item.official_sources.map(source => officialLink(source.url, '核对官方原文 ↗'))]));
  for (const [key, title] of [['roster_fragments', '本公告参会企业片段'], ['job_fragments', '本公告岗位片段']]) {
    const section = element('section', { className: 'detail-section' }, [element('h2', { text: title })]);
    const fragments = item[key] || [];
    if (!fragments.length) section.append(element('p', { className: 'source-message', text: '尚未取得可展示片段；不能据此判断没有企业或岗位。' }));
    for (const fragment of fragments) section.append(element('div', { className: 'material-fragment' }, [
      element('p', { className: 'scope-note', text: scopeText(fragment.scope) }), element('p', { className: 'source-text', text: fragment.text }),
      element('details', {}, [element('summary', { text: '查看片段依据' }), evidenceList(fragment.evidence)]),
    ]));
    content.append(section);
  }
  const attachments = element('section', { className: 'detail-section' }, [element('h2', { text: '适用的官方附件' })]);
  if (!item.attachments?.length) attachments.append(element('p', { className: 'source-message', text: '尚未取得已确认适用于本公告的附件。' }));
  for (const attachment of item.attachments || []) attachments.append(element('div', { className: 'material-fragment' }, [officialLink(attachment.url, `${attachment.label || '官方附件'} ↗`), element('p', { className: 'scope-note', text: scopeText(attachment.scope) }), element('details', {}, [element('summary', { text: '查看附件适用依据' }), evidenceList(attachment.evidence)])]));
  content.append(attachments);
  const coverage = element('section', { className: 'detail-section' }, [element('h2', { text: '材料与覆盖范围' }), element('p', { className: 'scope-note', text: scopeText(item.coverage) }), element('p', { className: 'source-message', text: '材料读取完整只针对所注明的材料，不代表整场、全校或全部岗位完整覆盖。' })]);
  for (const material of item.materials || []) coverage.append(element('details', { className: 'material-record' }, [
    element('summary', { text: `材料 ${material.id} · ${scopeText(material.scope)}` }), officialLink(material.source_url, '材料原文 ↗'),
    element('p', { className: 'material-hash', text: `SHA-256：${material.material_hash || '尚未取得'}` }),
    element('p', { className: 'source-message', text: `取得时间：${material.fetched_at || '尚未取得'}` }),
  ]));
  content.append(coverage);
  return content;
}
