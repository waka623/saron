/**
 * コピーライティング(投稿文・DM文言など)初稿生成のプロンプト組み立て。
 * グロースオペレーター設計図の「03 コピーライティング基礎」に対応。
 */

function buildCopywritingPrompt_(brief, aggregation, pastExamples) {
  const system = [
    'あなたはSNS発信者支援のコピーライターです。',
    '与えられたお題(投稿テーマ・ターゲット・フォーマットなど)から、投稿文・DM文言などの初稿を作成してください。',
    '',
    '使えるフレームワークの例(状況に応じて適切なものを選んでよい):',
    '- PASONA(Problem・Affinity・Solution・Offer・Narrowing down・Action)',
    '- AIDA(Attention・Interest・Desire・Action)',
    '',
    '制約:',
    '- 誇大表現・断定的な効果保証は避けること(「絶対に」「必ず痩せる」等は書かない)',
    '- これは初稿であり、実際に投稿・送信する文言としての最終確定は受け手が行うことを踏まえること',
    '- 2〜3パターンのバリエーションを出し、それぞれどんな切り口かを一言添えること',
    '- 出力は日本語、LINEで読みやすいプレーンテキスト(Markdown装飾は使わない)',
  ].join('\n');

  const userLines = ['## お題', brief];
  if (aggregation) {
    userLines.push('', '## 参考: 直近のSNS運用データ', formatKpiForPrompt_(aggregation.kpi), formatFunnelForPrompt_(aggregation.funnel));
  }
  if (pastExamples && pastExamples.length > 0) {
    userLines.push('', '## 過去に依頼者から評価された例(トーン・粒度の参考に)');
    pastExamples.forEach((ex, i) => {
      userLines.push(`例${i + 1}(${ex.feedback}):`, `入力: ${ex.input}`, `出力: ${ex.output}`, '');
    });
  }
  userLines.push('', '上記のお題に沿って、投稿文・DM文言などの初稿を2〜3パターン作成してください。');

  return { system, user: userLines.join('\n') };
}
