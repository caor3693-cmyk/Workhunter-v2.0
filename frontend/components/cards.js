import { element, opportunityPath, safePublicURL } from './dom.js';

export const FIELD_LABELS = { published_date: '公告发布时间', event_date: '活动日期', start_time: '开始时刻', end_time: '结束时刻', deadline: '投递截止', event_venue: '举办地点', work_locations: '工作地点' };
const UNKNOWN = { not_collected: '暂未取得', pending_extraction: '待核实', parse_failed: '待核实', not_disclosed: '原文未披露', conflict: '待核实（材料有冲突）' };
const KINDS = { campus_talk: '线下宣讲会', job_fair: '双选会 / 招聘会', online_recruitment: '线上招聘', announcement: '招聘公告' };
const SCOPES = { partial: '部分材料', complete_for_material: '本份材料已完整读取，非整场或全校完整覆盖', complete_for_page: '本页已读取，非全校覆盖', source_list: '栏目列表', unknown: '范围待核实', this_announcement: '本公告', disclosed_employers: '本公告已披露企业', partial_disclosed: '本公告部分披露', college_supplemental: '学院补充来源，非全校覆盖' };
function validEvidence(evidence) {
  return Array.isArray(evidence) && evidence.length > 0 && evidence.every(proof => proof && safePublicURL(proof.source_url) && proof.locator && proof.excerpt && proof.scope);
}

export function fieldFact(item, field) {
  const observation = item.field_observations?.[field];
  const state = observation?.state || 'not_collected';
  if (state === 'not_applicable') return { state, text: null, value: null };
  const evidence = observation?.evidence;
  const value = observation?.value;
  const validValue = field === 'work_locations' ? Array.isArray(value) && value.length > 0 && value.every(place => typeof place === 'string' && place.trim()) : typeof value === 'string' && value.trim();
  if (state !== 'known' || !validValue || !validEvidence(evidence)) return { state: state === 'known' ? 'pending_extraction' : state, text: UNKNOWN[state] || '待核实', value: null };
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
  if (typeof scope === 'string') return SCOPES[scope] || '范围待核实';
  if (!scope || typeof scope !== 'object') return '范围待核实';
  const parts = [];
  for (const key of ['completeness', 'coverage', 'type', 'kind', 'scope']) {
    if (typeof scope[key] === 'string' && SCOPES[scope[key]]) parts.push(SCOPES[scope[key]]);
  }
  if (scope.school_wide === false) parts.push('非全校覆盖');
  if (scope.window && typeof scope.window === 'object') parts.push([scope.window.from, scope.window.to].filter(day => typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day)).join(' 至 '));
  return [...new Set(parts.filter(Boolean))].join(' · ') || '范围待核实';
}

export function detailContent(item) {
  const content = element('div', { className: 'announcement-detail' }, [element('p', { className: 'card-school', text: [item.school_name || '学校归属待核实', KINDS[item.kind] || '类型待核实', item.campus_name].filter(Boolean).join(' · ') })]);
  const rows = [];
  for (const [field, label] of Object.entries(FIELD_LABELS)) {
    const fact = fieldFact(item, field);
    if (fact.text === null) continue;
    rows.push({ label: field === 'work_locations' && (item.kind === 'job_fair' || item.work_locations_scope !== 'this_announcement') ? '已披露工作地点' : label,
      text: fact.text + (field === 'work_locations' && item.work_locations_scope === 'partial_disclosed' ? '（披露不完整）' : '') });
  }
  if (item.event_status === 'cancelled') rows.push({ label: '活动状态', text: '官方已取消' });
  if (item.event_status === 'rescheduled') rows.push({ label: '活动状态', text: '官方已改期' });
  content.append(element('section', { className: 'detail-section' }, [element('h2', { text: '本公告信息' }), factList(rows)]));
  const sources = Array.isArray(item.official_sources) ? item.official_sources : [];
  const urls = [...new Set([item.source_url, ...sources.map(source => source?.url)].filter(url => safePublicURL(url)))];
  content.append(element('section', { className: 'detail-section' }, [element('h2', { text: '官方原文' }), ...(urls.length ? urls.map(url => officialLink(url)) : [element('p', { className: 'source-message', text: '官方链接待核实' })])]));
  for (const [key, title] of [['roster_fragments', '本公告参会企业片段'], ['job_fragments', '本公告岗位片段']]) {
    const section = element('section', { className: 'detail-section' }, [element('h2', { text: title })]);
    const supplied = Array.isArray(item[key]) ? item[key] : [];
    const fragments = supplied.filter(fragment => fragment && typeof fragment.text === 'string' && fragment.text.trim() && validEvidence(fragment.evidence));
    if (!fragments.length) section.append(element('p', { className: 'source-message', text: '尚未取得可展示片段；不能据此判断没有企业或岗位。' }));
    for (const fragment of fragments) section.append(element('div', { className: 'material-fragment' }, [
      element('p', { className: 'scope-note', text: scopeText(fragment.scope) }), element('p', { className: 'source-text', text: fragment.text }),
    ]));
    if (fragments.length < supplied.length) section.append(element('p', { className: 'source-message', text: '部分材料仍待核实，暂未展示。' }));
    content.append(section);
  }
  const attachments = element('section', { className: 'detail-section' }, [element('h2', { text: '适用的官方附件' })]);
  const supplied = Array.isArray(item.attachments) ? item.attachments : [];
  const applicable = supplied.filter(attachment => attachment && safePublicURL(attachment.url) && validEvidence(attachment.evidence));
  if (!applicable.length) attachments.append(element('p', { className: 'source-message', text: '尚未取得已确认适用于本公告的附件。' }));
  for (const attachment of applicable) attachments.append(element('div', { className: 'material-fragment' }, [officialLink(attachment.url, `${attachment.label || '官方附件'} ↗`), element('p', { className: 'scope-note', text: scopeText(attachment.scope) })]));
  if (applicable.length < supplied.length) attachments.append(element('p', { className: 'source-message', text: '部分附件适用关系待核实，暂未展示。' }));
  content.append(attachments);
  const coverage = element('section', { className: 'detail-section' }, [element('h2', { text: '材料与覆盖范围' }), element('p', { className: 'scope-note', text: scopeText(item.coverage) }), element('p', { className: 'source-message', text: '材料读取完整只针对所注明的材料，不代表整场、全校或全部岗位完整覆盖。' })]);
  content.append(coverage);
  return content;
}
