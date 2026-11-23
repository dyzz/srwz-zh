/** Original proportional story boxes in native 640×448 display coordinates.
 * ADV bevel samples are the inner grey edge measured on an empty ARMSX2 frame.
 * Map dialogue terminates at the physical right edge of the display.
 */
import {storyInkData} from './story-ink-data.mjs';
const advRight = [
  612, 617, 611, 616, 610, 615, 609, 614, 608, 613,
  607, 606, 606, 605, 605, 604, 604, 603, 603, 602,
  602, 601, 600, 600, 600, 599, 598, 598, 598, 597,
  596, 596, 596, 595, 594, 594, 593, 593, 592, 592,
  592, 591, 590, 590, 590, 589, 588, 588, 588, 587,
  586, 586, 586, 585, 584, 584, 584, 583, 582, 582,
  582, 581, 587, 580, 580, 579, 585, 578, 578, 577,
  583, 576, 576, 575, 581, 574, 574, 573, 579, 572,
];

const frames = {
  story: {x: 80, y: 346, narrowestRight: Math.min(...advRight)},
  story_map: {x: 206, y: 342, narrowestRight: 639},
};
const screenWidth = 640;
const tolerance = 1;  // Antialiasing and the sampled bevel introduce about one native pixel of uncertainty.
const edgeDistance = 4;

export function hasStoryInkProfile(scene, options) {
  return Object.hasOwn(frames, scene) && options.typography === 'proportional' &&
    options.chinesePunctuation === 'compact' && options.storyInk !== false;
}

/** Distances use the continuous right edge of the ink; a panel pixel at x ends at x + 1. */
export function storyRowInk(row, index, scene, font = 'hans') {
  const frame = frames[scene];
  let margin = Infinity;
  let screenMargin = Infinity;
  let uncertain = false;
  let dynamic = false;
  for (const glyph of row.glyphs) {
    if (glyph.text === ' ' || glyph.text === '　') continue;
    if (glyph.placeholder) dynamic = true;
    const left = frame.x + glyph.x;
    // If the entire quad clears even the narrowest part of the frame, its ink clears it too.
    if (left + glyph.width < frame.narrowestRight - edgeDistance) continue;
    const contour = glyph.bank ? storyInkData.bank[glyph.text.normalize('NFKC')] :
      storyInkData.common[glyph.text] ?? storyInkData[font]?.[glyph.text];
    if (!contour || dynamic || index >= 3) {
      uncertain = true;
      continue;
    }
    const top = frame.y + 28 * index + 2 * (glyph.yOffset ?? 0) + (glyph.baselineResidual16 ?? 0) / 16;
    const yScale = 2 * glyph.height / 24;
    for (let sy = 0; sy < 24; sy++) {
      const end = contour.charCodeAt(sy) - 65;
      if (!end) continue;
      const right = left + end * glyph.width / 24;
      screenMargin = Math.min(screenMargin, screenWidth - right);
      if (scene === 'story_map') {
        margin = screenMargin;
        continue;
      }
      const startY = Math.floor(top + sy * yScale);
      const endY = Math.ceil(top + (sy + 1) * yScale);
      for (let y = startY; y < endY; y++) {
        const boundary = advRight[y - frames.story.y];
        if (boundary === undefined) uncertain = true;
        else margin = Math.min(margin, boundary + 1 - right);
      }
    }
  }
  let status = 'fits';
  if (screenMargin < -tolerance) status = 'clipped';
  else if (margin < -tolerance) status = 'outside';
  else if (uncertain || Math.abs(margin) <= tolerance) status = 'uncertain';
  else if (margin <= edgeDistance) status = 'edge';
  return {
    status,
    // A null margin means the whole quad was already safe or that no contour was available.
    marginPx: Number.isFinite(margin) ? margin : null,
    ...(dynamic ? {basis: 'placeholder-reservation'} : {}),
  };
}
