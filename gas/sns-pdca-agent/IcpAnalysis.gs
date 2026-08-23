/**
 * LINE経由のICP分析。「ICP分析」に続けて顧客データを送ると、
 * ICP仮説をLINEに返信 + Google Docsにペルソナシートとして保存する。
 * ICPの採用判断は人が行う(このエージェントは仮説のドラフトまで)。
 */

function isIcpAnalysisCommand_(text) {
  return /^ICP分析/.test(text);
}

function handleIcpAnalysisRequest_(userId, text) {
  const rawData = text.replace(/^ICP分析\s*/, '').trim();
  if (!rawData) {
    return [
      '顧客データが見つかりませんでした。1行目に「ICP分析」、続けてデータを送ってください。',
      '',
      '例:',
      'ICP分析',
      'フォロワー属性: 25-34歳女性が62%',
      '既存顧客アンケート: 時間がなくて続かないという声が多い',
      'DMでよくある質問: リバウンドが怖い',
    ].join('\n');
  }

  const aggregation = getLastAggregation_(userId);
  const prompt = buildIcpPrompt_(rawData, aggregation);
  const personaText = callClaudeConversation_(prompt.system, [{ role: 'user', content: prompt.user }]);

  let docUrl = null;
  try {
    docUrl = writeIcpPersonaToDocs_(rawData, personaText);
  } catch (err) {
    Logger.log(`ICPペルソナシートのDocs書き出しに失敗しました: ${err}`);
  }

  const lines = [personaText];
  if (docUrl) {
    lines.push('', `ペルソナシートを保存しました: ${docUrl}`);
  }
  lines.push('', 'これは仮説のドラフトです。実際にこのICPで進めるかはご判断ください。');
  return lines.join('\n');
}

function writeIcpPersonaToDocs_(rawData, personaText) {
  const title = `【ICP仮説】${formatDate_(new Date())}`;
  const doc = DocumentApp.create(title);

  if (CONFIG.OUTPUT_FOLDER_ID) {
    moveFileToFolder_(doc.getId(), CONFIG.OUTPUT_FOLDER_ID);
  }

  const body = doc.getBody();
  body.clear();
  body.appendParagraph(title).setHeading(DocumentApp.ParagraphHeading.HEADING1);

  body.appendParagraph('入力した顧客データ').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendParagraph(rawData);

  body.appendParagraph('ICP仮説').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  appendMarkdownAsParagraphs_(body, personaText);

  body.appendHorizontalRule();
  body
    .appendParagraph('本シートはAIによる仮説のドラフトです。採用するICPは必ず確認のうえ判断してください。')
    .setItalic(true);

  doc.saveAndClose();
  return doc.getUrl();
}
