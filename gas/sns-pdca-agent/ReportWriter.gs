/**
 * レポート素案の組み立て・書き出し
 * 出力はあくまで「素案」。自動送信はしない(人が確認・仕上げ・送信する)。
 */

function buildReportSections_(aggregation, insightMarkdown) {
  return {
    title: `【週次レポート素案】${aggregation.account} ${formatDate_(aggregation.period.thisWeek.start)}〜${formatDate_(aggregation.period.thisWeek.end)}`,
    summary: buildSummarySection_(aggregation),
    kpi: aggregation.kpi,
    funnel: aggregation.funnel,
    insightMarkdown,
  };
}

function buildSummarySection_(aggregation) {
  const { funnel } = aggregation;
  const parts = [];
  if (funnel.highlight && funnel.highlight.status === 'up') {
    parts.push(`今週は${funnel.highlight.label}が好調でした(増減率 ${formatPct_(funnel.highlight.pctChange)})。`);
  }
  if (funnel.bottleneck && funnel.bottleneck.status === 'down') {
    parts.push(`一方、${funnel.bottleneck.label}が伸び悩んでいます(増減率 ${formatPct_(funnel.bottleneck.pctChange)})。`);
  }
  if (parts.length === 0) {
    parts.push('今週は各指標とも大きな変動はありませんでした。');
  }
  return parts.join('');
}

function writeReportToDocs_(aggregation, insightMarkdown) {
  const sections = buildReportSections_(aggregation, insightMarkdown);
  const doc = DocumentApp.create(sections.title);

  if (CONFIG.OUTPUT_FOLDER_ID) {
    moveFileToFolder_(doc.getId(), CONFIG.OUTPUT_FOLDER_ID);
  }

  const body = doc.getBody();
  body.clear();

  body.appendParagraph(sections.title).setHeading(DocumentApp.ParagraphHeading.HEADING1);

  body.appendParagraph('1. サマリ').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendParagraph(sections.summary);

  body.appendParagraph('2. KPI集計(当週 / 前週 / 増減率)').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  appendKpiTable_(body, sections.kpi);

  body.appendParagraph('3. AARRR分析').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  appendFunnelList_(body, sections.funnel);

  body.appendParagraph('4. 示唆の叩き台').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  appendMarkdownAsParagraphs_(body, sections.insightMarkdown);

  body.appendHorizontalRule();
  body
    .appendParagraph('本レポートはAIによる自動生成の素案です。クライアントへの送信前に必ず内容を確認・調整してください。')
    .setItalic(true);

  doc.saveAndClose();
  return doc.getUrl();
}

function appendKpiTable_(body, kpi) {
  const rows = [['指標', '当週', '前週', '増減率']];
  KPI_METRIC_KEYS_.forEach((key) => {
    const v = kpi[key];
    rows.push([v.label, formatValue_(v.current), formatValue_(v.previous), formatPct_(v.pctChange)]);
  });
  body.appendTable(rows);
}

function appendFunnelList_(body, funnel) {
  funnel.stages.forEach((s) => {
    const line =
      s.status === 'no_data'
        ? `${s.label}: データなし(${s.note})`
        : `${s.label}: ${statusLabel_(s.status)}(増減率 ${formatPct_(s.pctChange)})`;
    body.appendListItem(line);
  });
  if (funnel.bottleneck) {
    body.appendParagraph(`ボトルネック候補: ${funnel.bottleneck.label}`).setBold(true);
  }
}

function appendMarkdownAsParagraphs_(body, markdown) {
  const lines = (markdown || '').split('\n');
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    if (trimmed.startsWith('## ')) {
      body.appendParagraph(trimmed.replace(/^##\s+/, '')).setHeading(DocumentApp.ParagraphHeading.HEADING3);
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      body.appendListItem(trimmed.replace(/^[-*]\s+/, '').replace(/\*\*/g, ''));
    } else {
      body.appendParagraph(trimmed.replace(/\*\*/g, ''));
    }
  });
}

function moveFileToFolder_(fileId, folderId) {
  const file = DriveApp.getFileById(fileId);
  const folder = DriveApp.getFolderById(folderId);
  folder.addFile(file);
  DriveApp.getRootFolder().removeFile(file);
}

function writeReportToSheet_(aggregation, insightMarkdown) {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  let sheet = ss.getSheetByName(CONFIG.OUTPUT_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.OUTPUT_SHEET_NAME);
    sheet.appendRow(['作成日時', 'アカウント', '対象週', 'サマリ', 'KPI(JSON)', 'AARRR(JSON)', '示唆(Markdown)']);
  }

  const sections = buildReportSections_(aggregation, insightMarkdown);
  sheet.appendRow([
    new Date(),
    aggregation.account,
    `${formatDate_(aggregation.period.thisWeek.start)}〜${formatDate_(aggregation.period.thisWeek.end)}`,
    sections.summary,
    JSON.stringify(sections.kpi),
    JSON.stringify(sections.funnel),
    insightMarkdown,
  ]);

  return `${ss.getUrl()}#gid=${sheet.getSheetId()}`;
}
