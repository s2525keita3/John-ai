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
  CHANNEL_NAME:       'ぴゅあの日常',
  DEFAULT_TAGS:       '訪問看護,看護師,ぴゅあの日常,訪問看護ステーション,高円寺',
  HASHTAGS:           '#Shorts #訪問看護 #看護師の日常 #ぴゅあの日常',
  FOOTER:
    '\n\n---\n' +
    '訪問看護ステーションぴゅあの、ふだんの一日を切り取ってお届けしています。\n' +
    '一緒に働く仲間を募集中です。気になった方はプロフィールのリンクからどうぞ。\n',
  MAX_FILE_MB:        '50',  // Apps Script のファイル上限（約50MB）
  SELF_DECLARED_MADE_FOR_KIDS: 'false'
};

// 投稿キュー 列（0始まり）
const Q = {
  FILE_ID:  0,
  FILENAME: 1,
  SIZE_MB:  2,
  TITLE:    3,  // 空なら自動生成
  DESC:     4,  // 空なら自動生成
  STATUS:   5,  // 待機 | 保留 | 投稿済 | エラー
  NOTE:     6
};
const Q_HEADER = ['ファイルID', 'ファイル名', 'サイズ(MB)', 'タイトル', '説明文', 'ステータス', 'メモ'];
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
// =============================================================
// 01_Setup.gs  メニュー・初期化
// =============================================================

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('ショート投稿')
    .addItem('⓪ 投稿先チャンネルを確認',                 'checkChannel')
    .addItem('① 初期セットアップ（シート・フォルダ作成）', 'setupShorts')
    .addItem('② キューを更新（Driveを読む）',             'refreshQueue')
    .addSeparator()
    .addItem('③ 今すぐ1本投稿',                          'postOneNow')
    .addItem('④ 毎日自動投稿をON（トリガー作成）',        'installDailyTrigger')
    .addItem('　 毎日自動投稿をOFF',                      'removeDailyTrigger')
    .addToUi();
}

function setupShorts() {
  const ss = SpreadsheetApp.getActive();
  // 設定シート
  let st = ss.getSheetByName(SHORTS_SHEET.SETTINGS);
  if (!st) {
    st = ss.insertSheet(SHORTS_SHEET.SETTINGS);
    const rows = [['キー', '値', '説明']];
    const desc = {
      SOURCE_FOLDER_ID: '動画を入れるDriveフォルダのID',
      POSTED_FOLDER_NAME: '投稿済みを移すサブフォルダ名',
      FAILED_FOLDER_NAME: '投稿失敗を移すサブフォルダ名',
      POSTS_PER_RUN: '1回の実行で投稿する本数',
      PRIVACY_STATUS: 'public / unlisted / private',
      CHANNEL_NAME: '表示用',
      DEFAULT_TAGS: 'カンマ区切りタグ',
      HASHTAGS: '説明文末尾のハッシュタグ',
      FOOTER: '説明文の定型フッター',
      MAX_FILE_MB: 'この容量を超える動画は保留',
      SELF_DECLARED_MADE_FOR_KIDS: '子ども向けか（通常 false）',
      POST_HOUR: '自動投稿の時刻（0-23, 既定 19）'
    };
    for (const k of Object.keys(DEFAULTS)) rows.push([k, DEFAULTS[k], desc[k] || '']);
    rows.push(['POST_HOUR', '19', desc.POST_HOUR]);
    st.getRange(1, 1, rows.length, 3).setValues(rows);
    st.setColumnWidths(1, 3, 260);
  }
  // キュー・ログ
  ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  ensureSheet_(SHORTS_SHEET.LOG, LOG_HEADER);
  // サブフォルダ
  getOrCreateSubfolder_(getSetting_('POSTED_FOLDER_NAME'));
  getOrCreateSubfolder_(getSetting_('FAILED_FOLDER_NAME'));
  refreshQueue();
  SpreadsheetApp.getUi().alert('✅ セットアップ完了', '「投稿キュー」で文面を確認・編集できます。', SpreadsheetApp.getUi().ButtonSet.OK);
}

function ensureSheet_(name, header) {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function installDailyTrigger() {
  removeDailyTrigger();
  const hour = Number(getSetting_('POST_HOUR') || 19);
  ScriptApp.newTrigger('postScheduled').timeBased().everyDays(1).atHour(hour).create();
  SpreadsheetApp.getUi().alert(`毎日 ${hour}時台に自動投稿します。`);
}

function removeDailyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'postScheduled')
    .forEach(t => ScriptApp.deleteTrigger(t));
}

// 投稿先チャンネル（このスクリプトを実行しているアカウントの既定チャンネル）を表示
function checkChannel() {
  const ch = getMyChannel_();
  const expected = getSetting_('CHANNEL_NAME');
  const ok = ch.title === expected;
  SpreadsheetApp.getUi().alert(
    ok ? '✅ 投稿先チャンネルOK' : '⚠️ 投稿先チャンネルが違います',
    `このアカウントの投稿先: ${ch.title}\n期待するチャンネル: ${expected}` +
    (ok ? '' : '\n\nYouTubeでアカウント切替して「ぴゅあの日常」を既定にするか、チャンネルを管理するGoogleアカウントで実行してください。投稿は止めてあります。'),
    SpreadsheetApp.getUi().ButtonSet.OK);
}
// =============================================================
// 02_Queue.gs  Driveフォルダ → 投稿キュー
// =============================================================
// ソースフォルダ以下（サブフォルダも含む。投稿済み・エラーは除く）の動画をキューに追加する。
// 例：tiktok動画/26年10月/ジョン様/xxx.mp4
// 既にキューにあるファイルIDは触らない（手で編集した文面を守る）。

const VIDEO_MIME = ['video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm'];

function refreshQueue() {
  const sh = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  const existing = new Set(sh.getDataRange().getValues().slice(1).map(r => r[Q.FILE_ID]));
  const root = DriveApp.getFolderById(getSetting_('SOURCE_FOLDER_ID'));
  const maxMb = Number(getSetting_('MAX_FILE_MB'));
  const rows = [];
  for (const f of listVideosRecursive_(root)) {
    if (!VIDEO_MIME.includes(f.getMimeType()) || existing.has(f.getId())) continue;
    const mb = Math.round(f.getSize() / 1048576 * 10) / 10;
    const caption = buildCaption_(f.getName());
    rows.push([
      f.getId(), f.getName(), mb,
      caption.title, caption.description,
      mb > maxMb ? '保留' : '待機',
      mb > maxMb ? `容量超過（上限 ${maxMb}MB）` : ''
    ]);
  }
  // ファイル名順（日付が入っていれば古い順に）
  rows.sort((a, b) => String(a[Q.FILENAME]).localeCompare(String(b[Q.FILENAME]), 'ja'));
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, Q_HEADER.length).setValues(rows);
  return rows.length;
}

function listVideosRecursive_(folder) {
  const skip = [getSetting_('POSTED_FOLDER_NAME'), getSetting_('FAILED_FOLDER_NAME')];
  const out = [];
  const files = folder.getFiles();
  while (files.hasNext()) out.push(files.next());
  const subs = folder.getFolders();
  while (subs.hasNext()) {
    const sub = subs.next();
    if (!skip.includes(sub.getName())) out.push(...listVideosRecursive_(sub));
  }
  return out;
}

function getOrCreateSubfolder_(name) {
  const parent = DriveApp.getFolderById(getSetting_('SOURCE_FOLDER_ID'));
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function moveToSubfolder_(file, name) {
  file.moveTo(getOrCreateSubfolder_(name));
}
// =============================================================
// 03_Caption.gs  文面（タイトル・説明文）の自動生成
// =============================================================
// ファイル名からキーワードを拾い、テーマ別テンプレで文面を作る。
// 「投稿キュー」でタイトル・説明文を手で直せば、そちらが優先される。

const THEMES = [
  { keys: ['朝', 'おはよう', '出勤', '準備'],
    title: '訪問看護師の朝、こんな感じで始まります',
    body:  '出勤してからの準備の様子です。今日はどんな一日になるかな。' },
  { keys: ['移動', '自転車', '車', '雨', '道'],
    title: '訪問と訪問のあいだ、移動中のひとこま',
    body:  '訪問看護は移動も仕事のうち。季節や天気を感じながら次のお宅へ向かいます。' },
  { keys: ['カンファ', '会議', 'ミーティング', '申し送り'],
    title: 'チームで話す時間が、いいケアにつながる',
    body:  '申し送りやカンファレンスの様子。ひとりで抱えない、がぴゅあの大事にしていることです。' },
  { keys: ['新人', '研修', '同行', '教育', 'OJT'],
    title: '新人さんの同行訪問、こうやって育てています',
    body:  '最初はベテランと一緒に。少しずつ、安心してひとりで訪問できるようになっていきます。' },
  { keys: ['ランチ', '昼', 'お弁当', 'ごはん', 'おやつ', 'カフェ'],
    title: '訪問看護師のお昼休み',
    body:  '合間のひと息。みんなでごはんを食べる時間も、ぴゅあの日常です。' },
  { keys: ['帰り', '退勤', 'おつかれ', '夜', '終わり'],
    title: '今日もおつかれさまでした',
    body:  '一日の終わり。記録を書いて、明日の準備をして、おつかれさまです。' },
  { keys: ['リハ', 'OT', 'PT', '作業療法', '理学療法'],
    title: '訪問リハビリのリアル',
    body:  'リハ職も一緒に訪問しています。看護とリハが同じチームにいる強みがあります。' },
  { keys: ['採用', '面接', '募集', '仲間', '見学'],
    title: '一緒に働く仲間を探しています',
    body:  'ぴゅあの雰囲気、少しでも伝わればうれしいです。見学も歓迎しています。' }
];

const FALLBACK = {
  title: '訪問看護ステーションぴゅあ、今日のひとこま',
  body:  'ふだんの一日の中から、ちょっとした場面をお届けします。'
};

function buildCaption_(filename) {
  const base = filename.replace(/\.[^.]+$/, '');
  const theme = THEMES.find(t => t.keys.some(k => base.includes(k))) || FALLBACK;

  // ファイル名に日付（YYYYMMDD / YYYY-MM-DD / MMDD）があれば説明文に添える
  let dateNote = '';
  const m = base.match(/(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})/);
  if (m) dateNote = `${Number(m[2])}月${Number(m[3])}日の様子です。\n`;

  // ファイル名に「_」や「-」で区切られた自由文があれば短い見出しとして拾う
  const human = base
    .replace(/(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})/g, '')
    .replace(/^(IMG|VID|MOV|DSC|tiktok|TikTok)[_-]?\d*/i, '')
    .replace(/[_\-]+/g, ' ')
    .trim();

  let title = theme.title;
  if (human && human.length >= 4 && human.length <= 40 && !/^\d+$/.test(human)) {
    title = `${human}｜${getSetting_('CHANNEL_NAME')}`;
  }
  // YouTubeタイトルは100文字まで。#Shorts をタイトル末尾に付ける
  title = (title + ' #Shorts').slice(0, 100);

  const description =
    theme.body + '\n' + dateNote +
    getSetting_('FOOTER') + '\n' +
    getSetting_('HASHTAGS');

  return { title, description };
}
// =============================================================
// 04_Post.gs  YouTube へアップロード（YouTube Data API 高度なサービス）
// =============================================================
// 事前準備：Apps Script エディタ「サービス」→ YouTube Data API v3 を追加。
// 実行アカウントは「ぴゅあの日常」チャンネルを持つ Google アカウント。

function postScheduled() {
  refreshQueue();
  const n = Number(getSetting_('POSTS_PER_RUN') || 1);
  for (let i = 0; i < n; i++) {
    if (!postNext_()) break;
  }
}

function postOneNow() {
  refreshQueue();
  const ok = postNext_();
  SpreadsheetApp.getUi().alert(ok ? '✅ 1本投稿しました。「投稿ログ」を確認してください。' : '投稿できる動画（ステータス=待機）がありません。');
}

// 「待機」の先頭1件を投稿。成功時 true
function postNext_() {
  const sh = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  const data = sh.getDataRange().getValues();
  const idx = data.findIndex((r, i) => i > 0 && r[Q.STATUS] === '待機');
  if (idx < 0) return false;

  // 安全装置：投稿先が「ぴゅあの日常」でなければ何もしない
  const ch = getMyChannel_();
  if (ch.title !== getSetting_('CHANNEL_NAME')) {
    appendLog_([new Date(), '', '', '', '', '停止', `投稿先チャンネルが「${ch.title}」のため中止`]);
    return false;
  }

  const row = data[idx];
  const rowNo = idx + 1;
  const fileId = row[Q.FILE_ID];

  try {
    const file = DriveApp.getFileById(fileId);
    const auto = buildCaption_(file.getName());
    const title = String(row[Q.TITLE] || auto.title).slice(0, 100);
    const description = String(row[Q.DESC] || auto.description).slice(0, 5000);
    const tags = getSetting_('DEFAULT_TAGS').split(',').map(s => s.trim()).filter(Boolean);

    const resource = {
      snippet: { title, description, tags, categoryId: '22', defaultLanguage: 'ja' },
      status: {
        privacyStatus: getSetting_('PRIVACY_STATUS'),
        selfDeclaredMadeForKids: getSetting_('SELF_DECLARED_MADE_FOR_KIDS') === 'true'
      }
    };
    const res = YouTube.Videos.insert(resource, 'snippet,status', file.getBlob());
    const url = `https://youtube.com/shorts/${res.id}`;

    moveToSubfolder_(file, getSetting_('POSTED_FOLDER_NAME'));
    sh.getRange(rowNo, Q.STATUS + 1).setValue('投稿済');
    sh.getRange(rowNo, Q.NOTE + 1).setValue(url);
    appendLog_([new Date(), file.getName(), res.id, url, title, '成功', '']);
    return true;
  } catch (e) {
    sh.getRange(rowNo, Q.STATUS + 1).setValue('エラー');
    sh.getRange(rowNo, Q.NOTE + 1).setValue(e.message);
    appendLog_([new Date(), row[Q.FILENAME], '', '', row[Q.TITLE], '失敗', e.message]);
    try { moveToSubfolder_(DriveApp.getFileById(fileId), getSetting_('FAILED_FOLDER_NAME')); } catch (_) {}
    // クォータ超過は以降の投稿も無理なので停止
    if (/quota/i.test(e.message)) return false;
    return true; // 他の動画は続ける
  }
}

function appendLog_(row) {
  ensureSheet_(SHORTS_SHEET.LOG, LOG_HEADER).appendRow(row);
}

function getMyChannel_() {
  const res = YouTube.Channels.list('snippet', { mine: true });
  if (!res.items || !res.items.length) throw new Error('このアカウントにYouTubeチャンネルがありません');
  return { id: res.items[0].id, title: res.items[0].snippet.title };
}
