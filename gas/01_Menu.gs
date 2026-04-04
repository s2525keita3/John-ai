// =============================================================
// 01_Menu.gs  メニュー
// =============================================================

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('経費取込')
    .addItem('① 初期チェック',    'runInitialCheck')
    .addSeparator()
    .addItem('② RAW取込実行',     'runImport')
    .addSeparator()
    .addItem('集計を再計算',       'runRecalcSummary')
    .addToUi();
}

// ---------------------------------------------------------------
// ① 初期チェック
// ---------------------------------------------------------------
function runInitialCheck() {
  const ui = SpreadsheetApp.getUi();
  try {
    const errors = validateAll_();
    if (errors.length === 0) {
      ui.alert('✅ チェック完了', '必須シート・設定セルに問題はありません。', ui.ButtonSet.OK);
    } else {
      ui.alert('⚠️ チェック結果', errors.join('\n'), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert('エラー', e.message, ui.ButtonSet.OK);
  }
}

// ---------------------------------------------------------------
// ② RAW取込実行
// ---------------------------------------------------------------
function runImport() {
  const ui = SpreadsheetApp.getUi();

  const errors = validateAll_();
  if (errors.length > 0) {
    ui.alert('⚠️ 設定エラー', '先に初期チェックを実行してください:\n' + errors.join('\n'), ui.ButtonSet.OK);
    return;
  }

  const result = ui.alert('確認', 'RAW明細を取込みます。現在の RAW明細は上書きされます。実行しますか？', ui.ButtonSet.YES_NO);
  if (result !== ui.Button.YES) return;

  try {
    importAll_();
    ui.alert('✅ 完了', '取込が完了しました。「ログ」シートで詳細を確認してください。', ui.ButtonSet.OK);
  } catch (e) {
    logError_('runImport', e.message);
    ui.alert('❌ エラー', e.message, ui.ButtonSet.OK);
  }
}

// ---------------------------------------------------------------
// 集計再計算
// ---------------------------------------------------------------
function runRecalcSummary() {
  const ui = SpreadsheetApp.getUi();
  try {
    recalcSummary_();
    ui.alert('✅ 完了', '集計を更新しました。', ui.ButtonSet.OK);
  } catch (e) {
    ui.alert('❌ エラー', e.message, ui.ButtonSet.OK);
  }
}
