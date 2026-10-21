// =============================================================
// 00_Config.gs  ぴゅあの日常 ショート自動投稿  定数・設定
// =============================================================
// スプレッドシートの「設定」シート（A列=キー, B列=値）から読む。
// 未設定の項目は DEFAULTS を使う。

const SHORTS_SHEET = {
  SETTINGS: '設定',
  QUEUE:    '投稿キュー',   // 未投稿動画の一覧（文面を事前編集できる）
  LOG:      '投稿ログ'
};

const DEFAULTS = {
  SOURCE_FOLDER_ID:   '1yen3BdkhBFfGbAVcNKC3RCz_--aHbNcd', // tiktok動画
  POSTED_FOLDER_NAME: '01_投稿済み',
  FAILED_FOLDER_NAME: '99_エラー',
  POSTS_PER_RUN:      '1',          // 1回の実行で投稿する本数
  PRIVACY_STATUS:     'public',     // public | unlisted | private
  TRIAL_UNLISTED_COUNT: '3',        // 最初のN本は限定公開で出す（確認用）
  RECRUIT_URL:        '',           // 概要欄に載せる採用ページURL（要確認・空なら載せない）
  CHANNEL_NAME:       'ぴゅあの日常',
  DEFAULT_TAGS:       '訪問看護,看護師,ぴゅあの日常,訪問看護ステーション,高円寺',
  HASHTAGS:           '#Shorts #訪問看護 #看護師の日常 #ぴゅあの日常',
  FOOTER:
    '\n\n---\n' +
    '訪問看護ステーションぴゅあの、ふだんの一日を切り取ってお届けしています。\n' +
    '一緒に働く仲間を募集中です。見学も歓迎しています。\n',
  MAX_FILE_MB:        '500', // これを超える動画は保留（小分け送信なので大きくても可。実行時間6分に注意）
  SELF_DECLARED_MADE_FOR_KIDS: 'false'
};

// 投稿キュー 列（0始まり）
const Q = {
  FILE_ID:  0,
  FILENAME: 1,
  SIZE_MB:  2,
  TITLE:    3,  // 空なら自動生成
  DESC:     4,  // 空なら自動生成
  STATUS:   5,  // 未承認 | 承認 | 保留 | 投稿済 | エラー（「承認」だけ投稿される）
  NOTE:     6,
  DATE:     7   // 動画の日付（Driveの作成日と更新日の古いほう）。古い順に投稿する
};
const Q_HEADER = ['ファイルID', 'ファイル名', 'サイズ(MB)', 'タイトル', '説明文', 'ステータス', 'メモ', '動画の日付'];
const STATUS_LIST = ['未承認', '承認', '保留', '投稿済', 'エラー'];
const LOG_HEADER = ['日時', 'ファイル名', '動画ID', 'URL', 'タイトル', '結果', '詳細'];

function getSetting_(key) {
  const sh = SpreadsheetApp.getActive().getSheetByName(SHORTS_SHEET.SETTINGS);
  if (sh) {
    const rows = sh.getDataRange().getValues();
    for (const r of rows) {
      if (String(r[0]).trim() === key && String(r[1]).trim() !== '') return String(r[1]).trim();
    }
  }
  return DEFAULTS[key];
}
