// 校验 timeline.ts 里手写的 voice 帧数是否与 public/voice 下的真实 mp3 一致。
//
// 这个脚本是「旁白被截断」缺陷的守门人：timeline.ts 的构建期断言只能保证
// duration ≥ voice + 10，但如果 voice 本身写小了（比如换了文案却没更新），
// 断言照样通过、旁白照样被切。所以必须实测。
//
// 用法：node verify-timeline.mjs
import {parseMedia} from '@remotion/media-parser';
import {nodeReader} from '@remotion/media-parser/node';
import {readFile} from 'node:fs/promises';
import path from 'node:path';

const FPS = 30;
const MIN_TAIL = 10;

const source = await readFile(path.resolve('src/ps5/timeline.ts'), 'utf8');
const entryRe =
  /(\w+):\s*\{\s*voice:\s*(\d+),\s*duration:\s*(\d+),\s*audio:\s*'([^']+)'\s*\}/g;

const entries = [...source.matchAll(entryRe)].map((m) => ({
  key: m[1],
  voice: Number(m[2]),
  duration: Number(m[3]),
  audio: m[4],
}));

if (entries.length === 0) {
  console.error('没解析到任何 segment，检查 timeline.ts 的写法是否变了');
  process.exit(1);
}

let failed = 0;
console.log('段名        实测帧  写入帧  总帧  余量  结果');
for (const e of entries) {
  const {durationInSeconds} = await parseMedia({
    src: path.resolve('public', e.audio),
    fields: {durationInSeconds: true},
    reader: nodeReader,
    acknowledgeRemotionLicense: true,
  });
  const actual = Math.ceil((durationInSeconds ?? 0) * FPS);
  const tail = e.duration - actual;
  const voiceOk = Math.abs(actual - e.voice) <= 2;
  const tailOk = tail >= MIN_TAIL;
  const ok = voiceOk && tailOk;
  if (!ok) failed++;
  const note = ok ? 'OK' : !voiceOk ? `voice 写小了/大了 (实测 ${actual})` : `余量只有 ${tail}f`;
  console.log(
    e.key.padEnd(11),
    String(actual).padStart(6),
    String(e.voice).padStart(6),
    String(e.duration).padStart(5),
    String(tail).padStart(5),
    ` ${note}`,
  );
}

if (failed > 0) {
  console.error(`\n${failed} 段不合格：请更新 timeline.ts 的 voice/duration 后重排 from。`);
  process.exit(1);
}
console.log('\n全部合格：没有任何一段会切掉旁白。');
