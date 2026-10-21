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
