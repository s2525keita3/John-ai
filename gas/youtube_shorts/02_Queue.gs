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
