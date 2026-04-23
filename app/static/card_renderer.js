(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const CARD_W = 1461;
  const CARD_H = 1076;
  const MASTER_FRONT_FRAME = '/static/card_templates/shared/front_frame_main.png';
  const MASTER_BACK_FRAME = '/static/card_templates/shared/back_frame_main.png';
  const SLOT_LAYOUTS = {
    front: {
      base_frame: { x: 0, y: 0, w: CARD_W, h: CARD_H },
    },
    back: {
      base_frame: { x: 0, y: 0, w: CARD_W, h: CARD_H },
    },
  };
  const OVERLAY_SLOTS = new Set();

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function chunkText(text, lineLength, maxLines) {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const lines = [];
    let current = '';
    for (const word of words) {
      const next = current ? `${current} ${word}` : word;
      if (next.length > lineLength && current) {
        lines.push(current);
        current = word;
      } else {
        current = next;
      }
      if (lines.length === maxLines) break;
    }
    if (current && lines.length < maxLines) lines.push(current);
    return lines.slice(0, maxLines);
  }

  function textLines(lines, x, y, lineHeight, size, extra = '') {
    return lines.map((line, idx) =>
      `<text x="${x}" y="${y + (idx * lineHeight)}" font-size="${size}" ${extra}>${esc(line)}</text>`
    ).join('');
  }

  function rarityFilledCount(rarity) {
    const normalized = String(rarity || '').trim().toLowerCase();
    return ({
      common: 1,
      uncommon: 2,
      rare: 3,
      legendary: 4,
      mythic: 5,
      cryptic: 5,
      extinct: 5,
    })[normalized] || 1;
  }

  function formatDiscoveredText(data) {
    const region = String(data.region || '').trim();
    const capturedAt = String(data.captured_at || '').trim();
    let dateText = '';
    if (capturedAt) {
      const parsed = new Date(capturedAt);
      if (!Number.isNaN(parsed.getTime())) {
        dateText = parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
      }
    }
    return [dateText, region].filter(Boolean).join(' | ') || 'WildEx field log';
  }

  function inatHref(data) {
    if (data.inat_url) return data.inat_url;
    if (data.taxon_id) return `https://www.inaturalist.org/taxa/${encodeURIComponent(data.taxon_id)}`;
    const query = data.scientific_name || data.species_name || '';
    if (!query) return '';
    return `https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(query)}`;
  }

  function markerSvg(data) {
    const markers = Array.isArray(data.local_markers) ? data.local_markers : [];
    return markers.map((marker) => {
      const x = Number(marker.x || 0);
      const y = Number(marker.y || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
      return `
        <circle cx="${x}" cy="${y}" r="5" fill="#7d4f2f" stroke="#f7eedb" stroke-width="2"></circle>
        <circle cx="${x}" cy="${y}" r="10" fill="none" stroke="#7d4f2f" stroke-width="2" opacity="0.45"></circle>
      `;
    }).join('');
  }

  function mapInnerSvg(data) {
    const markers = markerSvg(data);
    if (data.range_mode === 'region' && (data.range_regions || []).includes('AU')) {
      return `
        <rect width="220" height="140" rx="14" fill="#ecdab8"></rect>
        <path d="M52 70 L98 50 L152 58 L176 82 L162 108 L112 118 L62 106 L42 86 Z" fill="#a17d57" stroke="#6b4f35" stroke-width="4"></path>
        ${markers || '<circle cx="118" cy="84" r="6" fill="#7d4f2f" stroke="#f7eedb" stroke-width="2"></circle>'}`;
    }
    if (data.range_mode === 'ocean') {
      return `
        <rect width="220" height="140" rx="14" fill="#dae7ea"></rect>
        <rect x="6" y="6" width="208" height="128" rx="12" fill="#93c5d2"></rect>
        <path d="M10 20 L58 14 L72 42 L52 58 L18 54 Z" fill="#a59072"></path>
        <path d="M144 20 L208 24 L202 60 L160 70 L134 44 Z" fill="#a59072"></path>
        <path d="M70 86 L112 92 L122 126 L80 130 Z" fill="#a59072"></path>
        <path d="M18 96 C46 72, 74 74, 104 92 S158 104, 192 84" fill="none" stroke="#2e6d7b" stroke-width="16" stroke-linecap="round"></path>
        ${markers}`;
    }
    const ranges = new Set(data.range_regions || []);
    const fill = (code) => ranges.has(code) ? '#a17d57' : '#bcbcbc';
    return `
      <rect width="220" height="140" rx="14" fill="#dae7ea"></rect>
      <path d="M22 28 L50 18 L74 28 L82 48 L62 60 L34 58 L20 44 Z" fill="${fill('NA')}" stroke="#6b4f35" stroke-width="2"></path>
      <path d="M60 76 L76 82 L84 110 L72 126 L58 116 L52 92 Z" fill="${fill('SA')}" stroke="#6b4f35" stroke-width="2"></path>
      <path d="M92 24 L114 20 L126 28 L124 40 L98 38 Z" fill="${fill('EU')}" stroke="#6b4f35" stroke-width="2"></path>
      <path d="M96 46 L124 48 L136 84 L120 122 L96 108 L88 68 Z" fill="${fill('AF')}" stroke="#6b4f35" stroke-width="2"></path>
      <path d="M128 24 L176 24 L206 44 L194 70 L150 68 L130 50 Z" fill="${fill('AS')}" stroke="#6b4f35" stroke-width="2"></path>
      <path d="M168 90 L206 96 L212 116 L180 126 L160 114 Z" fill="${fill('AU')}" stroke="#6b4f35" stroke-width="2"></path>
      ${markers}`;
  }

  function mapSvg(data) {
    return `
      <svg xmlns="${SVG_NS}" viewBox="0 0 220 140" width="220" height="140">
        ${mapInnerSvg(data)}
      </svg>`;
  }

  function templateParts(template) {
    const parts = Array.isArray(template?.parts) ? template.parts.filter(Boolean) : [];
    if (parts.length) return parts.slice().sort((a, b) => Number(a?.sort_order || 100) - Number(b?.sort_order || 100));
    if (template?.asset_url) {
      return [{
        slot_name: 'base_frame',
        asset_url: template.asset_url,
        asset_type: 'template',
        sort_order: 0,
      }];
    }
    return [];
  }

  function baseFramePart(template, fallbackUrl) {
    const parts = templateParts(template);
    const base = parts.find((part) => (part.slot_name || 'base_frame') === 'base_frame');
    if (base?.asset_url) return base;
    if (template?.asset_url) {
      return { slot_name: 'base_frame', asset_url: template.asset_url, asset_type: 'template', sort_order: 0 };
    }
    return { slot_name: 'base_frame', asset_url: fallbackUrl, asset_type: 'template', sort_order: 0 };
  }

  function slotBox(side, slotName) {
    return SLOT_LAYOUTS[side]?.[slotName] || SLOT_LAYOUTS[side]?.base_frame || { x: 0, y: 0, w: CARD_W, h: CARD_H };
  }

  function slotZIndex(slotName) {
    if (slotName === 'frame_overlay') return 5;
    if (slotName === 'photo_frame') return 4;
    if (OVERLAY_SLOTS.has(slotName)) return 3;
    return 0;
  }

  function htmlPartLayers(template, side) {
    return templateParts(template).map((part) => {
      const box = slotBox(side, part.slot_name);
      const style = [
        `left:${(box.x / CARD_W) * 100}%`,
        `top:${(box.y / CARD_H) * 100}%`,
        `width:${(box.w / CARD_W) * 100}%`,
        `height:${(box.h / CARD_H) * 100}%`,
        `z-index:${slotZIndex(part.slot_name || 'base_frame')}`,
      ].join(';');
      return `
        <img
          class="wx-asset-layer slot-${esc(part.slot_name || 'base_frame')}"
          src="${esc(part.asset_url || '')}"
          alt=""
          style="${style}"
          data-slot="${esc(part.slot_name || 'base_frame')}"
        >`;
    }).join('');
  }

  function svgPartLayers(template, side, phase = 'underlay') {
    return templateParts(template).filter((part) => {
      const isOverlay = OVERLAY_SLOTS.has(part.slot_name || '');
      return phase === 'overlay' ? isOverlay : !isOverlay;
    }).map((part) => {
      const box = slotBox(side, part.slot_name);
      return `<image href="${esc(part.asset_url || '')}" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}" preserveAspectRatio="none"></image>`;
    }).join('');
  }

  async function assetToDataUrl(url) {
    if (!url) return '';
    const resp = await fetch(url, { credentials: 'same-origin' });
    if (!resp.ok) throw new Error(`Asset fetch failed: ${url}`);
    const blob = await resp.blob();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function frontSvg(data, templateTemplate, imageHref) {
    const namePlate = slotContent(data, 'name_plate', { title: data.species_name, subtitle: data.scientific_name });
    const abilities = (slotContent(data, 'abilities_panel', { rows: data.abilities }).rows || data.abilities || []).slice(0, 4);
    const statRows = Array.isArray(slotContent(data, 'stat_panel', {}).rows)
      ? slotContent(data, 'stat_panel', {}).rows
      : [
          { label: 'HP', value: data.hp },
          { label: 'ATK', value: data.atk },
          { label: 'DEF', value: data.def },
          { label: 'SPD', value: data.spd },
        ];
    const framePart = baseFramePart(templateTemplate, MASTER_FRONT_FRAME);
    const artHref = imageHref || data.image_url || '';
    const habitatLines = chunkText(data.habitat_text || '', 22, 2);
    const rarityText = String(data.rarity || '').toUpperCase();
    return `
      <svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
        <defs>
          <clipPath id="frontPhotoClip"><rect x="334" y="184" width="706" height="583" rx="18"></rect></clipPath>
        </defs>
        <image href="${esc(framePart.asset_url || MASTER_FRONT_FRAME)}" x="0" y="0" width="${CARD_W}" height="${CARD_H}" preserveAspectRatio="none"></image>
        ${artHref ? `<image href="${esc(artHref)}" x="334" y="184" width="706" height="583" preserveAspectRatio="xMidYMid slice" clip-path="url(#frontPhotoClip)"></image>` : ''}
        <text x="92" y="102" text-anchor="middle" font-size="58" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f7eedb">${esc(data.card_number || '')}</text>
        <text x="244" y="108" text-anchor="middle" font-size="30" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f7eedb" letter-spacing="1.8">${esc(rarityText)}</text>
        <text x="655" y="96" text-anchor="middle" font-size="66" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f7eedb">${esc(namePlate.title || data.species_name)}</text>
        <text x="655" y="156" text-anchor="middle" font-size="34" font-family="Georgia, serif" font-style="italic" fill="#e8d14f">${esc(namePlate.subtitle || data.scientific_name)}</text>
        <g transform="translate(1113 31) scale(1.25 0.95)">
          ${mapInnerSvg(data)}
        </g>
        ${statRows.slice(0, 4).map((row, idx) => `<text x="182" y="${315 + idx * 130}" text-anchor="end" font-size="54" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f2eadb">${esc(row.value ?? '')}</text>`).join('')}
        ${abilities.map((line, idx) => {
          const title = typeof line === 'string' ? line : line?.name || '';
          return `
            <text x="1143" y="${283 + idx * 130}" font-size="36" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f2eadb">${esc(title)}</text>
          `;
        }).join('')}
        ${textLines(habitatLines, 164, 958, 42, 30, 'fill="#f2eadb" font-family="Segoe UI, sans-serif" font-weight="700"')}
        <text x="727" y="958" text-anchor="middle" font-size="34" font-family="Segoe UI, sans-serif" font-weight="800" fill="#d9cfaf">${esc(data.banner_text || data.kingdom || '')}</text>
        <text x="1053" y="958" text-anchor="middle" font-size="34" font-family="Segoe UI, sans-serif" font-weight="800" fill="#d9cfaf">LVL 1</text>
        <text x="1300" y="958" text-anchor="middle" font-size="34" font-family="Segoe UI, sans-serif" font-weight="800" fill="#d9cfaf">XP 0/100</text>
      </svg>`;
  }

  function backSvg(data, templateTemplate, imageHref, qrHref) {
    const framePart = baseFramePart(templateTemplate, MASTER_BACK_FRAME);
    const namePlate = slotContent(data, 'name_plate', { title: data.species_name, subtitle: data.scientific_name });
    const aboutLines = chunkText(data.info_text || '', 30, 9);
    const dietLines = chunkText(data.diet_text || '', 21, 6);
    const activeLines = chunkText(data.biome_bonus || data.biome || '', 20, 2);
    const temperamentLines = chunkText(data.aggression || '', 20, 2);
    const quoteLines = chunkText(data.fact_text || '', 26, 2);
    const discoveredLines = chunkText(formatDiscoveredText(data), 20, 2);
    const mediaHref = imageHref || data.image_url || '';
    const qrImageHref = qrHref || data.qr_url || '';
    const filledDots = rarityFilledCount(data.rarity);
    return `
      <svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
        <defs>
          <clipPath id="backMediaClip"><rect x="539" y="39" width="498" height="731" rx="24"></rect></clipPath>
        </defs>
        <image href="${esc(framePart.asset_url || MASTER_BACK_FRAME)}" x="0" y="0" width="${CARD_W}" height="${CARD_H}" preserveAspectRatio="none"></image>
        ${mediaHref ? `<image href="${esc(mediaHref)}" x="539" y="39" width="498" height="731" preserveAspectRatio="xMidYMid slice" clip-path="url(#backMediaClip)" opacity="0.9"></image>` : ''}
        <text x="116" y="90" font-size="62" font-family="Segoe UI, sans-serif" font-weight="800" fill="#215633">${esc(namePlate.title || data.species_name)}</text>
        <text x="116" y="143" font-size="33" font-family="Georgia, serif" font-style="italic" fill="#1f1d18">${esc(namePlate.subtitle || data.scientific_name)}</text>
        ${textLines(aboutLines, 60, 236, 55, 26, 'fill="#4a4339" font-family="Segoe UI, sans-serif"')}
        <text x="220" y="779" font-size="36" font-family="Segoe UI, sans-serif" font-weight="800" fill="#215633">${esc(data.length_text || '')}</text>
        ${textLines(dietLines, 1147, 220, 52, 25, 'fill="#5f5648" font-family="Segoe UI, sans-serif"')}
        ${textLines(activeLines, 1124, 612, 44, 26, 'fill="#5f5648" font-family="Segoe UI, sans-serif"')}
        ${textLines(temperamentLines, 1124, 748, 44, 26, 'fill="#5f5648" font-family="Segoe UI, sans-serif"')}
        <text x="1362" y="101" text-anchor="middle" font-size="62" font-family="Segoe UI, sans-serif" font-weight="800" fill="#f7eedb">${esc(data.card_number || '')}</text>
        ${[0, 1, 2, 3, 4].map((idx) => `<circle cx="${78 + idx * 56}" cy="930" r="20" fill="${idx < filledDots ? '#8c9f35' : 'none'}" stroke="#7d6a45" stroke-width="3"></circle>`).join('')}
        ${textLines(quoteLines, 487, 932, 42, 26, 'fill="#d9cfaf" font-family="Georgia, serif" font-style="italic"')}
        ${textLines(discoveredLines, 869, 932, 42, 24, 'fill="#d9cfaf" font-family="Segoe UI, sans-serif"')}
        ${qrImageHref ? `<image href="${esc(qrImageHref)}" x="1176" y="844" width="121" height="121" preserveAspectRatio="none"></image>` : ''}
      </svg>`;
  }

  function mountSvgFace(target, svgMarkup, themeClass, sideClass) {
    target.className = ['wx-face', sideClass, themeClass].filter(Boolean).join(' ');
    target.innerHTML = svgMarkup;
  }

  function infoRowsHtml(data) {
    const rows = [
      ['Common Name', data.common_name || data.species_name],
      ['Scientific Name', data.scientific_name],
      ['Length', data.length_text],
      ['Habitat', data.habitat_text],
      ['Diet', data.diet_text],
    ];
    return rows.map(([label, value]) => `
      <div class="wx-info-row">
        <div class="wx-info-label">${esc(label)}</div>
        <div class="wx-info-value">${esc(value || '')}</div>
      </div>
    `).join('');
  }

  function listHtml(items) {
    return (items || []).slice(0, 3).map((item) => `<div class="wx-list-line">&#8226; ${esc(item)}</div>`).join('');
  }

  function triggerHtml(items) {
    return (items || []).slice(0, 2).map((item) => `<div class="wx-trigger-line">${esc(item)}</div>`).join('');
  }

  function slotContent(data, key, fallback = {}) {
    const slotMap = data.slot_content || {};
    return slotMap[key] || fallback;
  }

  function frontFaceHtml(data) {
    return frontSvg(data, data.front_template, data.image_url || '');
  }

  function backFaceHtml(data) {
    return backSvg(data, data.back_template, data.image_url || '', data.qr_url || '');
  }

  function renderErrorHtml(reason, data = {}) {
    const templatePath = data.front_template?.asset_url || data.back_template?.asset_url || 'missing';
    return `
      <div class="wx-render-error" role="alert">
        <strong>Card preview unavailable</strong>
        <span>${esc(reason || 'Unknown render failure')}</span>
        <code>template: ${esc(templatePath)}</code>
        <code>species: ${esc(data.species_name || 'Unknown')}</code>
      </div>`;
  }

  function buildCard(target, data) {
    if (!target) return null;
    try {
      if (!data) throw new Error('Card data missing');
      if (!templateParts(data.front_template).length || !templateParts(data.back_template).length) {
        throw new Error('Template asset missing');
      }
      const frontMarkup = frontSvg(data, data.front_template, data.image_url || '');
      const backMarkup = backSvg(data, data.back_template, data.image_url || '', data.qr_url || '');
      target.innerHTML = `
        <div class="wx-card-shell">
          <div class="wx-flip-card">
            <div class="wx-flip-inner">
              <div class="wx-face front ${esc(data.theme_class)}">${frontMarkup}</div>
              <div class="wx-face back ${esc(data.theme_class)}">${backMarkup}</div>
            </div>
          </div>
        </div>`;
      target.__wxData = data;
      if (!data.image_url) {
        console.warn('WildEx card render missing image', { dexId: data.dex_id, species: data.species_name });
      }
    } catch (error) {
      console.error('WildEx card render failed', { error, data });
      target.innerHTML = renderErrorHtml(error?.message || 'Card render failed', data);
      target.__wxData = data || null;
    }
    return target;
  }

  function flip(target) {
    const card = target.querySelector('.wx-flip-card');
    if (card) card.classList.toggle('flipped');
  }

  function printNode(node) {
    const frame = window.open('', '_blank', 'width=900,height=1200');
    if (!frame) return;
    frame.document.write(`<!doctype html><html><head><title>Print Card</title><style>body{margin:0;display:grid;place-items:center;background:#111}svg{width:88mm;height:auto;display:block}</style></head><body>${node.innerHTML}</body></html>`);
    frame.document.close();
    frame.focus();
    setTimeout(() => frame.print(), 250);
  }

  async function exportSvgToPng(svgNode, fileName) {
    const svgString = new XMLSerializer().serializeToString(svgNode);
    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = CARD_W * 2;
    canvas.height = CARD_H * 2;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    const link = document.createElement('a');
    link.href = URL.createObjectURL(png);
    link.download = fileName;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1500);
  }

  async function svgToPngBlob(svgNode) {
    const svgString = new XMLSerializer().serializeToString(svgNode);
    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = CARD_W * 2;
    canvas.height = CARD_H * 2;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  }

  async function exportFace(target, side, nameBase) {
    const data = target.__wxData;
    const templateSource = side === 'front' ? data.front_template : data.back_template;
    const convertedParts = await Promise.all(templateParts(templateSource).map(async (part) => ({
      ...part,
      asset_url: await assetToDataUrl(part.asset_url || ''),
    })));
    const imageHref = data.image_url ? await assetToDataUrl(data.image_url || '') : '';
    const qrHref = side === 'back' && data.qr_url ? await assetToDataUrl(data.qr_url) : '';
    const svgMarkup = side === 'front'
      ? frontSvg(data, { ...templateSource, parts: convertedParts }, imageHref)
      : backSvg(data, { ...templateSource, parts: convertedParts }, imageHref, qrHref);
    const temp = document.createElement('div');
    temp.innerHTML = svgMarkup.trim();
    await exportSvgToPng(temp.firstElementChild, `${nameBase}-${side}.png`);
  }

  async function exportBoth(target, nameBase) {
    await exportFace(target, 'front', nameBase);
    await exportFace(target, 'back', nameBase);
  }

  async function exportFaceBlob(target, side) {
    const data = target.__wxData;
    const templateSource = side === 'front' ? data.front_template : data.back_template;
    const convertedParts = await Promise.all(templateParts(templateSource).map(async (part) => ({
      ...part,
      asset_url: await assetToDataUrl(part.asset_url || ''),
    })));
    const imageHref = data.image_url ? await assetToDataUrl(data.image_url || '') : '';
    const qrHref = side === 'back' && data.qr_url ? await assetToDataUrl(data.qr_url) : '';
    const svgMarkup = side === 'front'
      ? frontSvg(data, { ...templateSource, parts: convertedParts }, imageHref)
      : backSvg(data, { ...templateSource, parts: convertedParts }, imageHref, qrHref);
    const temp = document.createElement('div');
    temp.innerHTML = svgMarkup.trim();
    return svgToPngBlob(temp.firstElementChild);
  }

  function sampleCards() {
    const makeTemplates = (kingdom) => ({
      front_template: {
        name: `naturalist-front-v1`,
        version: '1.0.0',
        asset_url: MASTER_FRONT_FRAME,
      },
      back_template: {
        name: `naturalist-back-v1`,
        version: '1.0.0',
        asset_url: MASTER_BACK_FRAME,
      },
    });

    return [
      {
        species_name: 'Ring-tailed Dragon',
        scientific_name: 'Ctenophorus caudicinctus',
        common_name: 'Ring-tailed Dragon',
        dex_id: 'AU-REP-DRG-017',
        card_number: '17',
        rarity: 'Rare',
        threat_level: 'Medium',
        aggression: 'Medium',
        length_text: '8-10 inches (20-25 cm)',
        habitat_text: 'Rocky terrain of arid Australian outback',
        diet_text: 'Insects and small invertebrates',
        info_text: 'Ring-tailed Dragon is a small, spiny lizard found in the arid regions of Australia. Its long banded tail helps it blend in with the rocky environment.',
        fact_text: 'Can wag its banded tail to mimic a scurrying insect, distracting predators.',
        image_url: '',
        sound_url: '',
        hp: 48, atk: 42, def: 58, spd: 64,
        type_label: 'Reptile', biome: 'Rocky Desert', biome_bonus: '+20% defence in arid zones',
        strength_name: 'Desert', strength_effect: '+20% defence in arid zones',
        weakness_name: 'Cold Rain', weakness_effect: 'Reduced mobility and warmth in wet conditions',
        abilities: ['Flatten Body', 'Band-tail Decoy'],
        environment_triggers: ['Gains advantage in rocky desert terrain', 'Vulnerable to cold rain conditions'],
        range_mode: 'region', range_regions: ['AU'], local_markers: [{ region: 'AU', x: 79, y: 60 }],
        theme_class: 'theme-reptile', banner_text: 'DRAGON',
        ...makeTemplates('reptile'),
      },
      {
        species_name: 'Red Kangaroo', scientific_name: 'Macropus rufus', common_name: 'Red Kangaroo',
        dex_id: 'AU-MAM-MAR-018', card_number: '18', rarity: 'Common', threat_level: 'Medium', aggression: 'High',
        length_text: '1.0-1.6 m body length', habitat_text: 'Arid plains and open woodland', diet_text: 'Grasses and low vegetation',
        info_text: 'Red Kangaroo is the largest living marsupial and dominates inland Australian plains with powerful hind legs and efficient movement.',
        fact_text: 'Can cover long distances with energy-saving hops across arid terrain.',
        image_url: '', sound_url: '', hp: 75, atk: 65, def: 45, spd: 70,
        type_label: 'Mammal', biome: 'Grassland', biome_bonus: '+20% damage in arid zones',
        strength_name: 'Desert', strength_effect: '+20% damage in arid zones',
        weakness_name: 'Heavy Rain', weakness_effect: 'Reduced mobility and dodge in wet conditions',
        abilities: ['Powerful Kick', 'Hop Away'],
        environment_triggers: ['Gains advantage in desert terrain', 'Vulnerable in heavy rain'],
        range_mode: 'region', range_regions: ['AU'], local_markers: [{ region: 'AU', x: 102, y: 84 }],
        theme_class: 'theme-mammal', banner_text: 'PAW',
        ...makeTemplates('mammal'),
      },
      {
        species_name: 'Great White Shark', scientific_name: 'Carcharodon carcharias', common_name: 'Great White Shark',
        dex_id: 'AU-FSH-SHK-003', card_number: '003', rarity: 'Legendary', threat_level: 'Extreme', aggression: 'High',
        length_text: '3.5-6.0 m', habitat_text: 'Coastal shelf waters and offshore marine zones', diet_text: 'Fish, rays, and marine mammals',
        info_text: 'Great White Shark is an apex marine predator built for bursts of speed and powerful ambush strikes from below.',
        fact_text: 'Uses electroreception to detect prey movement in murky water.',
        image_url: '', sound_url: '', hp: 84, atk: 92, def: 62, spd: 78,
        type_label: 'Marine', biome: 'Ocean Current', biome_bonus: '+20% speed in open water',
        strength_name: 'Open Water', strength_effect: '+20% speed in marine zones',
        weakness_name: 'Shallow Heat', weakness_effect: 'Reduced endurance in warm shallow water',
        abilities: ['Burst Rush', 'Ambush Bite'],
        environment_triggers: ['Gains advantage in marine terrain', 'Vulnerable to shallow heat conditions'],
        range_mode: 'ocean', range_regions: ['PACIFIC', 'INDIAN', 'ATLANTIC'], local_markers: [],
        theme_class: 'theme-fish', banner_text: 'FISH',
        ...makeTemplates('fish'),
      },
      {
        species_name: 'Bald Eagle', scientific_name: 'Haliaeetus leucocephalus', common_name: 'Bald Eagle',
        dex_id: 'NA-BRD-RAP-004', card_number: '004', rarity: 'Rare', threat_level: 'High', aggression: 'High',
        length_text: '70-102 cm body length', habitat_text: 'Large lakes, coasts, and river systems', diet_text: 'Fish, birds, and carrion',
        info_text: 'Bald Eagle patrols large waterways with exceptional eyesight and powerful diving strikes.',
        fact_text: 'Builds some of the largest nests used by any bird species.',
        image_url: '', sound_url: '', hp: 64, atk: 74, def: 52, spd: 83,
        type_label: 'Bird', biome: 'Sky / Cliff', biome_bonus: '+20% speed in open air',
        strength_name: 'High Wind', strength_effect: '+20% scouting in elevated terrain',
        weakness_name: 'Dense Brush', weakness_effect: 'Reduced maneuvering in enclosed canopy',
        abilities: ['High Scan', 'Dive Strike'],
        environment_triggers: ['Gains advantage in elevated terrain', 'Vulnerable to dense brush conditions'],
        range_mode: 'world', range_regions: ['NA'], local_markers: [{ region: 'NA', x: 34, y: 36 }],
        theme_class: 'theme-bird', banner_text: 'WING',
        ...makeTemplates('bird'),
      },
      {
        species_name: 'Giant Praying Mantis', scientific_name: 'Hierodula majuscula', common_name: 'Giant Praying Mantis',
        dex_id: 'AU-INS-INS-008', card_number: '008', rarity: 'Uncommon', threat_level: 'Medium', aggression: 'Medium',
        length_text: '6-10 cm', habitat_text: 'Shrubland, gardens, and dry grassland', diet_text: 'Insects and small arthropods',
        info_text: 'Giant Praying Mantis waits motionless before snapping out with spined forelegs to seize prey.',
        fact_text: 'Excellent camouflage lets it disappear among stems and leaves.',
        image_url: '', sound_url: '', hp: 28, atk: 46, def: 38, spd: 58,
        type_label: 'Insect', biome: 'Brushland', biome_bonus: '+20% evasion in dense foliage',
        strength_name: 'Camouflage', strength_effect: '+20% evasion in natural cover',
        weakness_name: 'Cold Snap', weakness_effect: 'Reduced activity in low temperatures',
        abilities: ['Ambush Grab', 'Leaf Stillness'],
        environment_triggers: ['Gains advantage in brushland terrain', 'Vulnerable to cold snap conditions'],
        range_mode: 'region', range_regions: ['AU'], local_markers: [{ region: 'AU', x: 94, y: 78 }],
        theme_class: 'theme-insect', banner_text: 'INSECT',
        ...makeTemplates('insect'),
      },
      {
        species_name: 'Pitcher Plant', scientific_name: 'Nepenthes rafflesiana', common_name: 'Pitcher Plant',
        dex_id: 'AS-PLT-BOT-011', card_number: '011', rarity: 'Cryptic', threat_level: 'Low', aggression: 'Low',
        length_text: 'Pitchers to 30 cm', habitat_text: 'Humid wetlands and nutrient-poor ground', diet_text: 'Insects trapped in pitcher fluid',
        info_text: 'Pitcher Plant grows ornate pitfall traps that lure insects with colour, scent, and nectar.',
        fact_text: 'Digestive fluid inside the pitcher breaks down trapped prey for nutrients.',
        image_url: '', sound_url: '', hp: 42, atk: 36, def: 54, spd: 22,
        type_label: 'Plant', biome: 'Botanical Habitat', biome_bonus: '+20% resilience in native soil',
        strength_name: 'Rooted Soil', strength_effect: '+20% resilience in stable ground',
        weakness_name: 'Transplant Shock', weakness_effect: 'Reduced vitality outside native habitat',
        abilities: ['Pitfall Trap', 'Digestive Pool'],
        environment_triggers: ['Gains advantage in humid terrain', 'Vulnerable to transplant shock conditions'],
        range_mode: 'world', range_regions: ['AS'], local_markers: [{ region: 'AS', x: 139, y: 48 }],
        theme_class: 'theme-plant', banner_text: 'LEAF',
        ...makeTemplates('plant'),
      },
    ];
  }

  window.WildExCardRenderer = {
    buildCard,
    flip,
    printNode,
    exportFace,
    exportBoth,
    exportFaceBlob,
    sampleCards,
  };
})();
