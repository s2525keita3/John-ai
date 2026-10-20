// =============================================================
// 02_Queue.gs  Driveフォルダ → 投稿キュー
// =============================================================
// ソースフォルダ直下の動画ファイルをキューに追加する。
// 既にキューにあるファイルIDは触らない（手で編集した文面を守る）。

const VIDEO_MIME = ['video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm'];

function refreshQueue() {
  const sh = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  const existing = new Set(sh.getDataRange().getValues().slice(1).map(r => r[Q.FILE_ID]));
  const folder = DriveApp.getFolderById(getSetting_('SOURCE_FOLDER_ID'));
  const maxMb = Number(getSetting_('MAX_FILE_MB'));
  const files = folder.getFiles();
  const rows = [];
  while (files.hasNext()) {
    const f = files.next();
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

function getOrCreateSubfolder_(name) {
  const parent = DriveApp.getFolderById(getSetting_('SOURCE_FOLDER_ID'));
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function moveToSubfolder_(file, name) {
  file.moveTo(getOrCreateSubfolder_(name));
}
