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
