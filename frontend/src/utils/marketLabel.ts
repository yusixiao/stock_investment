/**
 * 市场显示标签统一映射。
 *
 * 后端持久化 / API 字段使用大写英文标识(A / HK / US / HK_CONNECT),
 * 前端 UI 一律走 marketLabel() 输出中文,避免各处散落硬编码。
 */
const LABELS: Record<string, string> = {
  A: 'A 股',
  HK: '港股',
  US: '美股',
  HK_CONNECT: '港股通',
};

export function marketLabel(market: string | null | undefined): string {
  if (!market) return '';
  const key = market.toUpperCase();
  return LABELS[key] ?? market;
}
