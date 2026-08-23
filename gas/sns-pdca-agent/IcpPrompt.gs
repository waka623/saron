/**
 * ICP(Ideal Customer Profile)仮説抽出のプロンプト組み立て。
 * グロースオペレーター設計図の「02 ICP設計」に対応。
 * 他のプロンプトと同様、調整しやすいようここだけ切り出してある。
 */

function buildIcpPrompt_(rawCustomerData, aggregation, pastExamples) {
  const system = [
    'あなたはSNS発信者支援のグロースマーケターの分析パートナーです。',
    '与えられた顧客データから、ICP(Ideal Customer Profile)の仮説を抽出してください。',
    '',
    '分析の観点:',
    '- デモグラフィック(年齢層・性別・居住地など、データにあれば)',
    '- 心理的トリガー(購買のきっかけ・悩み・欲求)',
    '- 優良顧客(継続購入・満足度が高い顧客)に共通する特徴',
    '- 購買前に抱えている悩みと、購買後に得られる変化',
    '',
    '制約:',
    '- データから読み取れる範囲で仮説として提示すること。データに無い情報を創作しない',
    '- ICPの採用可否は受け手が判断するものであることを踏まえ、断定しすぎない(「〜と考えられる」)',
    '- データの量・質に応じて仮説の確度(高い/中程度/低い)を明記すること',
    '- 出力は日本語、LINEで読みやすいプレーンテキスト(Markdown装飾は使わない)',
    '- 次の見出しに沿って出力すること: 「デモグラフィック」「抱えている悩み」「購買トリガー」「優良顧客の共通点」「仮説の確度」',
  ].join('\n');

  const userLines = ['## 顧客データ', rawCustomerData];
  if (aggregation) {
    userLines.push('', '## 参考: 直近のSNS運用データ', formatKpiForPrompt_(aggregation.kpi), formatFunnelForPrompt_(aggregation.funnel));
  }
  if (pastExamples && pastExamples.length > 0) {
    userLines.push('', '## 過去に依頼者から評価された例(トーン・粒度の参考に)');
    pastExamples.forEach((ex, i) => {
      userLines.push(`例${i + 1}(${ex.feedback}):`, `入力: ${ex.input}`, `出力: ${ex.output}`, '');
    });
  }
  userLines.push('', '上記からICP仮説を抽出してください。');

  return { system, user: userLines.join('\n') };
}
