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
      POSTS_PER_RUN: '1回の実行で投稿する本数（ストックが多いときは2まで。1本1〜2分かかり、実行は6分で打ち切られる）',
      PRIVACY_STATUS: 'public / unlisted / private',
      TRIAL_UNLISTED_COUNT: '最初のこの本数は限定公開で投稿',
      RECRUIT_URL: '概要欄に載せる採用ページURL',
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
  const q = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  q.getRange(2, Q.STATUS + 1, 1000, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(STATUS_LIST, true).build());
  q.setColumnWidth(Q.TITLE + 1, 320).setColumnWidth(Q.DESC + 1, 420);
  ensureSheet_(SHORTS_SHEET.LOG, LOG_HEADER);
  // サブフォルダ
  getOrCreateSubfolder_(getSetting_('POSTED_FOLDER_NAME'));
  getOrCreateSubfolder_(getSetting_('FAILED_FOLDER_NAME'));
  refreshQueue();
  SpreadsheetApp.getUi().alert('✅ セットアップ完了', '「投稿キュー」で動画と文面を確認し、投稿してよいものだけステータスを「承認」にしてください。', SpreadsheetApp.getUi().ButtonSet.OK);
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
      mb > maxMb ? '保留' : '未承認',
      mb > maxMb ? `容量超過（上限 ${maxMb}MB）` : '',
      videoDate_(f)
    ]);
  }
  // 古い順に並べる
  rows.sort((a, b) => a[Q.DATE] - b[Q.DATE]);
  // ファイル名をクリックで動画が開けるリンクにする（承認時に中身を確認するため）
  for (const r of rows) {
    const url = DriveApp.getFileById(r[Q.FILE_ID]).getUrl();
    r[Q.FILENAME] = `=HYPERLINK("${url}","${String(r[Q.FILENAME]).replace(/"/g, '')}")`;
  }
  if (rows.length) {
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, Q_HEADER.length).setValues(rows);
    // 表全体を古い順に並べ直す（あとから古い動画が追加されても順番が崩れないように）
    if (sh.getLastRow() > 2) {
      sh.getRange(2, 1, sh.getLastRow() - 1, Q_HEADER.length).sort({ column: Q.DATE + 1, ascending: true });
    }
  }
  return rows.length;
}

// 動画の日付：Drive の作成日と更新日のうち古いほう
// （アップロードし直した動画は作成日が新しくなるが、更新日に元の日付が残ることが多い）
function videoDate_(f) {
  const c = f.getDateCreated(), u = f.getLastUpdated();
  return c < u ? c : u;
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
  if (human && human.length >= 4 && human.length <= 40 && !/^[A-Za-z0-9 ]+$/.test(human)) {
    title = `${human}｜${getSetting_('CHANNEL_NAME')}`;
  }
  // YouTubeタイトルは100文字まで。#Shorts をタイトル末尾に付ける
  title = (title + ' #Shorts').slice(0, 100);

  const description =
    theme.body + '\n' + dateNote +
    getSetting_('FOOTER') +
    (getSetting_('RECRUIT_URL') ? `採用情報: ${getSetting_('RECRUIT_URL')}\n` : '') + '\n' +
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
  SpreadsheetApp.getUi().alert(ok ? '✅ 1本投稿しました。「投稿ログ」を確認してください。' : '投稿できる動画（ステータス=承認）がありません。');
}

// 「承認」のうち一番古い動画を1件投稿。成功時 true
function postNext_() {
  const sh = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  const data = sh.getDataRange().getValues();
  let idx = -1;
  for (let i = 1; i < data.length; i++) {
    if (data[i][Q.STATUS] !== '承認') continue;
    if (idx < 0 || new Date(data[i][Q.DATE]) < new Date(data[idx][Q.DATE])) idx = i;
  }
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
    const fileName = file.getName();
    const auto = buildCaption_(file.getName());
    const title = String(row[Q.TITLE] || auto.title).slice(0, 100);
    const description = String(row[Q.DESC] || auto.description).slice(0, 5000);
    const tags = getSetting_('DEFAULT_TAGS').split(',').map(s => s.trim()).filter(Boolean);

    const resource = {
      snippet: { title, description, tags, categoryId: '22', defaultLanguage: 'ja' },
      status: {
        privacyStatus: countPosted_() < Number(getSetting_('TRIAL_UNLISTED_COUNT') || 0)
          ? 'unlisted' : getSetting_('PRIVACY_STATUS'),
        selfDeclaredMadeForKids: getSetting_('SELF_DECLARED_MADE_FOR_KIDS') === 'true'
      }
    };
    const videoId = uploadResumable_(file, resource);
    const url = `https://youtube.com/shorts/${videoId}`;
    sh.getRange(rowNo, Q.STATUS + 1).setValue('投稿済');

    // 投稿済みフォルダへ移動。他人がオーナーの動画は移動できないことがあるので、失敗しても投稿は成功扱い
    let moveNote = '';
    try { moveToSubfolder_(file, getSetting_('POSTED_FOLDER_NAME')); }
    catch (err) { moveNote = `（フォルダ移動できず：${err.message}）`; }
    sh.getRange(rowNo, Q.NOTE + 1).setValue(url + moveNote);
    appendLog_([new Date(), fileName, videoId, url, title, '成功', moveNote]);
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

function countPosted_() {
  const rows = ensureSheet_(SHORTS_SHEET.LOG, LOG_HEADER).getDataRange().getValues().slice(1);
  return rows.filter(r => r[5] === '成功').length;
}

// ---------------------------------------------------------------
// 大きな動画も送れるよう、8MBずつ小分けにして YouTube へ送る
// （Apps Script は一度に約50MBまでしか扱えないため）
// ---------------------------------------------------------------
const CHUNK = 8 * 1024 * 1024; // 256KB の倍数であること

function uploadResumable_(file, resource) {
  const token = ScriptApp.getOAuthToken();
  const total = file.getSize();
  const mime = file.getMimeType();

  // 1) 送信の受付窓口（セッション）を作る
  const init = UrlFetchApp.fetch(
    'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      headers: {
        Authorization: 'Bearer ' + token,
        'X-Upload-Content-Length': String(total),
        'X-Upload-Content-Type': mime
      },
      payload: JSON.stringify(resource),
      muteHttpExceptions: true
    });
  if (init.getResponseCode() !== 200) throw new Error('アップロード開始に失敗: ' + init.getContentText());
  const headers = init.getAllHeaders();
  const session = headers.Location || headers.location;

  // 2) Drive から8MBずつ読み、順に送る
  for (let start = 0; start < total; start += CHUNK) {
    const end = Math.min(start + CHUNK, total) - 1;
    const part = UrlFetchApp.fetch(
      `https://www.googleapis.com/drive/v3/files/${file.getId()}?alt=media&supportsAllDrives=true`, {
        headers: { Authorization: 'Bearer ' + token, Range: `bytes=${start}-${end}` },
        muteHttpExceptions: true
      });
    if (part.getResponseCode() !== 206 && part.getResponseCode() !== 200) {
      throw new Error('Driveからの読み込みに失敗: ' + part.getResponseCode());
    }
    const put = UrlFetchApp.fetch(session, {
      method: 'put',
      contentType: mime,
      headers: { 'Content-Range': `bytes ${start}-${end}/${total}` },
      payload: part.getBlob().getBytes(),
      muteHttpExceptions: true
    });
    const code = put.getResponseCode();
    if (code === 200 || code === 201) return JSON.parse(put.getContentText()).id;
    if (code !== 308) throw new Error(`送信に失敗（${code}）: ` + put.getContentText());
  }
  throw new Error('送信が完了しませんでした');
}
