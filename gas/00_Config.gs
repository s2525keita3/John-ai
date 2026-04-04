// =============================================================
// 00_Config.gs  定数・設定取得
// =============================================================

const SHEET = {
  SETTINGS:     '設定',
  OUTPUT:       '本部経費_横並び',
  RULES:        'マスタ_ルール',
  FIXED:        'マスタ_固定値',
  SHINKIN:      '信金_手入力',
  LOG:          'ログ'
};

const STATUS = {
  CONFIRMED:    '確定',
  UNCONFIRMED:  '未確定',
  UNREGISTERED: 'ルール未登録',
  EXCLUDED:     '除外'
};

// RAW明細列インデックス（0始まり）
const C = {
  KEIJO:     0,  // 計上月
  DATE:      1,  // 発生日
  SOURCE:    2,  // 取込元
  FILENAME:  3,  // ファイル名
  RAW_DESC:  4,  // 摘要原文
  NORM_DESC: 5,  // 正規化摘要
  AMOUNT:    6,  // 金額
  KAMOKU:    7,  // 勘定科目
  UCIWAKE:   8,  // 内訳
  HANTEI:    9,  // 判定
  STATUS:    10, // ステータス
  BIKO:      11  // 備考
};

const RAW_HEADER = [
  '計上月', '発生日', '取込元', 'ファイル名',
  '摘要原文', '正規化摘要', '金額',
  '勘定科目', '内訳', '判定', 'ステータス', '備考'
];

// RAWデータ出力開始行（1始まり）。上段を集計エリアとして確保
const RAW_START_ROW = 25;

const SORT_ORDER = { '確定': 1, '未確定': 2, 'ルール未登録': 3, '除外': 4 };

// ---------------------------------------------------------------
// 設定取得
// ---------------------------------------------------------------
function getSettings_() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET.SETTINGS);
  if (!sheet) throw new Error('「設定」シートが見つかりません');

  const keijoMonth = String(sheet.getRange('B2').getValue()).trim();
  const folderId   = String(sheet.getRange('B3').getValue()).trim();

  return { keijoMonth, folderId };
}
