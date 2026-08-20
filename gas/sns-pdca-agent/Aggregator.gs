/**
 * 週次集計: 前週比KPI・AARRRファネル分析
 */

function aggregateWeekly_(rows, account, now) {
  now = now || new Date();
  const thisWeek = getWeekRange_(now, 1); // 直近の完了週(トリガー実行時点で「先週」にあたる)
  const lastWeek = getWeekRange_(now, 2); // その前の週(比較対象)

  const filtered = account ? rows.filter((r) => r.account === account) : rows;

  const thisWeekRows = filtered.filter((r) => inRange_(r.date, thisWeek));
  const lastWeekRows = filtered.filter((r) => inRange_(r.date, lastWeek));

  const thisKpi = summarizeWeek_(thisWeekRows);
  const lastKpi = summarizeWeek_(lastWeekRows);

  const kpi = buildKpiComparison_(thisKpi, lastKpi);
  const funnel = buildAarrrAnalysis_(kpi);

  return {
    account: account || '(単一アカウント)',
    period: { thisWeek, lastWeek },
    rowCounts: { thisWeek: thisWeekRows.length, lastWeek: lastWeekRows.length },
    kpi,
    funnel,
  };
}

function getWeekRange_(baseDate, weeksAgo) {
  const d = new Date(baseDate);
  const day = d.getDay(); // 0=日 .. 6=土
  const diffToMonday = (day === 0 ? -6 : 1) - day;
  const thisMonday = new Date(d);
  thisMonday.setHours(0, 0, 0, 0);
  thisMonday.setDate(d.getDate() + diffToMonday);

  const start = new Date(thisMonday);
  start.setDate(thisMonday.getDate() - 7 * weeksAgo);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  end.setHours(23, 59, 59, 999);

  return { start, end };
}

function inRange_(date, range) {
  return date >= range.start && date <= range.end;
}

function summarizeWeek_(weekRows) {
  if (weekRows.length === 0) return emptyWeekSummary_();

  const sorted = weekRows.slice().sort((a, b) => a.date - b.date);
  const sum = (key) => sorted.reduce((acc, r) => acc + (r[key] || 0), 0);

  const reach = sum('reach');
  const impressions = sum('impressions');
  const likes = sum('likes');
  const saves = sum('saves');
  const comments = sum('comments');
  const shares = sum('shares');
  const profileAccess = sum('profileAccess');
  const engagementTotal = likes + saves + comments + shares;
  const engagementRate = reach > 0 ? (engagementTotal / reach) * 100 : null;

  const followersEnd = sorted[sorted.length - 1].followers;
  const followersStart = sorted[0].followers;
  const followersNet =
    followersEnd !== null && followersEnd !== undefined && followersStart !== null && followersStart !== undefined
      ? followersEnd - followersStart
      : null;

  return {
    reach,
    impressions,
    likes,
    saves,
    comments,
    shares,
    profileAccess,
    engagementTotal,
    engagementRate,
    followersEnd,
    followersNet,
  };
}

function emptyWeekSummary_() {
  return {
    reach: null,
    impressions: null,
    likes: null,
    saves: null,
    comments: null,
    shares: null,
    profileAccess: null,
    engagementTotal: null,
    engagementRate: null,
    followersEnd: null,
    followersNet: null,
  };
}

const KPI_METRIC_KEYS_ = [
  'reach',
  'impressions',
  'likes',
  'saves',
  'comments',
  'shares',
  'profileAccess',
  'engagementTotal',
  'engagementRate',
  'followersEnd',
  'followersNet',
];

const KPI_LABELS_ = {
  reach: 'リーチ',
  impressions: 'インプレッション',
  likes: 'いいね',
  saves: '保存',
  comments: 'コメント',
  shares: 'シェア',
  profileAccess: 'プロフィールアクセス',
  engagementTotal: 'エンゲージメント合計',
  engagementRate: 'エンゲージメント率(%)',
  followersEnd: 'フォロワー数(週末時点)',
  followersNet: 'フォロワー純増数',
};

function buildKpiComparison_(thisKpi, lastKpi) {
  const result = {};
  KPI_METRIC_KEYS_.forEach((m) => {
    const current = valueOrNull_(thisKpi[m]);
    const previous = valueOrNull_(lastKpi[m]);
    result[m] = {
      label: KPI_LABELS_[m],
      current,
      previous,
      diff: current !== null && previous !== null ? current - previous : null,
      pctChange: pctChange_(current, previous),
    };
  });
  return result;
}

function valueOrNull_(v) {
  return v === undefined ? null : v;
}

function pctChange_(current, previous) {
  if (current === null || previous === null) return null;
  if (previous === 0) return current === 0 ? 0 : null; // ゼロ割は算出不能として扱う
  return ((current - previous) / Math.abs(previous)) * 100;
}

// AARRRの各段階と、判断に使うKPI指標の対応
const AARRR_STAGES_ = [
  { key: 'acquisition', label: 'Acquisition（新規リーチ）', metrics: ['reach', 'impressions'] },
  { key: 'activation', label: 'Activation（興味・行動喚起）', metrics: ['profileAccess', 'engagementRate'] },
  { key: 'retention', label: 'Retention（継続・フォロワー定着）', metrics: ['followersNet'] },
  { key: 'referral', label: 'Referral（紹介・拡散）', metrics: ['shares'] },
  { key: 'revenue', label: 'Revenue（売上）', metrics: [] }, // トラッカーに売上列が無い前提。将来拡張
];

const STATUS_UP_THRESHOLD_ = 5; // %
const STATUS_DOWN_THRESHOLD_ = -5; // %

function buildAarrrAnalysis_(kpi) {
  const stages = AARRR_STAGES_.map((stage) => {
    if (stage.metrics.length === 0) {
      return Object.assign({}, stage, {
        status: 'no_data',
        pctChange: null,
        note: 'トラッカーに該当する列が無いため対象外(将来拡張)',
      });
    }
    const pctChanges = stage.metrics
      .map((m) => kpi[m] && kpi[m].pctChange)
      .filter((v) => v !== null && v !== undefined && isFinite(v));
    if (pctChanges.length === 0) {
      return Object.assign({}, stage, { status: 'no_data', pctChange: null, note: 'データ不足' });
    }
    const avgPct = pctChanges.reduce((a, b) => a + b, 0) / pctChanges.length;
    const status = avgPct > STATUS_UP_THRESHOLD_ ? 'up' : avgPct < STATUS_DOWN_THRESHOLD_ ? 'down' : 'flat';
    return Object.assign({}, stage, { status, pctChange: avgPct });
  });

  const withData = stages.filter((s) => s.pctChange !== null);
  const bottleneck = withData.length
    ? withData.reduce((a, b) => (a.pctChange < b.pctChange ? a : b))
    : null;
  const highlight = withData.length
    ? withData.reduce((a, b) => (a.pctChange > b.pctChange ? a : b))
    : null;

  return { stages, bottleneck, highlight };
}

function statusLabel_(status) {
  return { up: '好調', down: '要注意', flat: '横ばい' }[status] || status;
}
