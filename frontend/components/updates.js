const count = value => Number.isSafeInteger(value) && value >= 0 ? String(value) : '待核实';

export function updatePresentation(data) {
  const today = data?.today || {};
  const categories = [
    ['current_new', '当前新收录'], ['historical_backfill', '历史补齐'], ['undated_new', '日期待核实'],
    ['official_changes', '官方变化'], ['parser_improvements', '解析改进'], ['evidence_conflicts', '材料冲突'],
    ['manual_supplements', '人工补录'], ['manual_corrections', '人工纠错'],
    ['manual_reverts', '撤回更正'], ['manual_withdrawals', '撤回人工可见贡献'],
  ];
  const detail = categories.filter(([key]) => key in today).map(([key, label]) => `${label} ${count(today[key])} 条`).join('，');
  return {
    newlyCollected: today.newly_collected ?? '—', officialChanges: today.official_changes ?? '—',
    message: [data?.message || '检查情况暂不可确认。', today.date ? `${today.date}（北京时间）` : '', detail,
      data?.categories_overlap && !data?.message?.includes('不可相加') ? '分类可能重叠，不可相加。' : ''].filter(Boolean).join(' '),
  };
}
