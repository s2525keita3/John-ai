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

// 「承認」の先頭1件を投稿。成功時 true
function postNext_() {
  const sh = ensureSheet_(SHORTS_SHEET.QUEUE, Q_HEADER);
  const data = sh.getDataRange().getValues();
  const idx = data.findIndex((r, i) => i > 0 && r[Q.STATUS] === '承認');
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
    const res = YouTube.Videos.insert(resource, 'snippet,status', file.getBlob());
    const url = `https://youtube.com/shorts/${res.id}`;

    moveToSubfolder_(file, getSetting_('POSTED_FOLDER_NAME'));
    sh.getRange(rowNo, Q.STATUS + 1).setValue('投稿済');
    sh.getRange(rowNo, Q.NOTE + 1).setValue(url);
    appendLog_([new Date(), fileName, res.id, url, title, '成功', '']);
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
