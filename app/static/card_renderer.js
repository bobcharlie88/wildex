(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const CARD_W = 750;
  const CARD_H = 1050;

  const MASTER_FRONT_FRAME = '/static/card_templates/shared/front_frame_main.png';
  const MASTER_BACK_FRAME = '/static/card_templates/shared/back_frame_main.png';

  const KINGDOM_THEMES = {
    'theme-reptile': {
      bg1: '#100806', bg2: '#2c1408', bg3: '#4a2010',
      accent: '#c07830', accent2: '#e0a858', accent3: '#f2d098',
      panel: 'rgba(38,16,6,0.92)', panelBorder: 'rgba(192,120,48,0.45)',
      text: '#f5e8d0', textMuted: '#c8a468', divider: 'rgba(192,120,48,0.4)',
    },
    'theme-mammal': {
      bg1: '#0e0b06', bg2: '#221a08', bg3: '#3a2c0e',
      accent: '#c09820', accent2: '#e0c050', accent3: '#f2e098',
      panel: 'rgba(26,18,6,0.92)', panelBorder: 'rgba(192,152,32,0.45)',
      text: '#f5eacc', textMuted: '#c8b068', divider: 'rgba(192,152,32,0.4)',
    },
    'theme-fish': {
      bg1: '#030810', bg2: '#081828', bg3: '#0c2840',
      accent: '#1880c0', accent2: '#50b8e8', accent3: '#98d8f8',
      panel: 'rgba(4,12,24,0.92)', panelBorder: 'rgba(24,128,192,0.45)',
      text: '#d0eaf8', textMuted: '#60a8d0', divider: 'rgba(24,128,192,0.4)',
    },
    'theme-bird': {
      bg1: '#080a12', bg2: '#101828', bg3: '#182038',
      accent: '#6878c8', accent2: '#98a8e0', accent3: '#ccd4f5',
      panel: 'rgba(10,12,22,0.92)', panelBorder: 'rgba(104,120,200,0.45)',
      text: '#e2e8f8', textMuted: '#8098c8', divider: 'rgba(104,120,200,0.4)',
    },
    'theme-insect': {
      bg1: '#0e0c06', bg2: '#201a04', bg3: '#342c08',
      accent: '#b08808', accent2: '#d8b028', accent3: '#f0d878',
      panel: 'rgba(18,14,4,0.92)', panelBorder: 'rgba(176,136,8,0.45)',
      text: '#f5ecc0', textMuted: '#c8b058', divider: 'rgba(176,136,8,0.4)',
    },
    'theme-plant': {
      bg1: '#030e06', bg2: '#081c0c', bg3: '#0c2e12',
      accent: '#209830', accent2: '#50c058', accent3: '#90e090',
      panel: 'rgba(4,14,6,0.92)', panelBorder: 'rgba(32,152,48,0.45)',
      text: '#d0f5d0', textMuted: '#68c070', divider: 'rgba(32,152,48,0.4)',
    },
  };

  const DEFAULT_THEME = KINGDOM_THEMES['theme-mammal'];

  function getTheme(themeClass) {
    return KINGDOM_THEMES[themeClass] || DEFAULT_THEME;
  }

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

  function rarityFilledCount(rarity) {
    const key = String(rarity || '').trim().toLowerCase();
    const counts = {
      common: 1, uncommon: 2, rare: 3, very_rare: 4, legendary: 4, mythic: 5, cryptic: 5, extinct: 5,
    };
    return counts[key] || 1;
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
    return [dateText, region].filter(Boolean).join(' · ') || 'WildEx field log';
  }

  function inatHref(data) {
    if (data.inat_url) return data.inat_url;
    if (data.taxon_id) return `https://www.inaturalist.org/taxa/${encodeURIComponent(data.taxon_id)}`;
    const query = data.scientific_name || data.species_name || '';
    if (!query) return '';
    return `https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(query)}`;
  }

  function markerSvg(data) {
    return (Array.isArray(data.local_markers) ? data.local_markers : []).map((m) => {
      const x = Number(m.x || 0);
      const y = Number(m.y || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
      return `<circle cx="${x}" cy="${y}" r="5" fill="#e07830" stroke="#f5e8d0" stroke-width="2"/>
              <circle cx="${x}" cy="${y}" r="10" fill="none" stroke="#e07830" stroke-width="1.5" opacity="0.45"/>`;
    }).join('');
  }

  function mapInnerSvg(data) {
    const markers = markerSvg(data);
    if (data.range_mode === 'region' && (data.range_regions || []).includes('AU')) {
      return `<rect width="200" height="120" rx="10" fill="#0e0a06"/>
              <path d="M46 60 L88 44 L138 52 L160 74 L148 98 L102 108 L56 96 L38 78 Z"
                    fill="#3a2010" stroke="#c07830" stroke-width="2.5"/>
              ${markers || '<circle cx="108" cy="76" r="5" fill="#e07830" stroke="#f5e8d0" stroke-width="2"/>'}`;
    }
    if (data.range_mode === 'ocean') {
      return `<rect width="200" height="120" rx="10" fill="#060e18"/>
              <rect x="5" y="5" width="190" height="110" rx="8" fill="#0c2030"/>
              <path d="M10 18 L52 12 L64 36 L46 50 L16 48 Z" fill="#142818"/>
              <path d="M130 18 L186 22 L182 54 L144 62 L122 40 Z" fill="#142818"/>
              <path d="M64 78 L100 84 L110 112 L72 116 Z" fill="#142818"/>
              <path d="M16 86 C42 64, 68 68, 96 84 S144 94, 176 76"
                    fill="none" stroke="#1880c0" stroke-width="12" stroke-linecap="round" opacity="0.5"/>
              ${markers}`;
    }
    const ranges = new Set(data.range_regions || []);
    const f = (c) => ranges.has(c) ? '#3a2010' : '#14100c';
    const s = (c) => ranges.has(c) ? '#c07830' : '#201c18';
    return `<rect width="200" height="120" rx="10" fill="#0e1214"/>
            <path d="M20 24 L46 14 L68 24 L74 44 L56 54 L30 52 L18 40 Z" fill="${f('NA')}" stroke="${s('NA')}" stroke-width="1.5"/>
            <path d="M54 68 L68 74 L76 100 L64 114 L52 104 L46 82 Z" fill="${f('SA')}" stroke="${s('SA')}" stroke-width="1.5"/>
            <path d="M84 20 L104 18 L114 24 L112 36 L88 34 Z" fill="${f('EU')}" stroke="${s('EU')}" stroke-width="1.5"/>
            <path d="M88 42 L112 44 L122 76 L108 110 L88 96 L80 62 Z" fill="${f('AF')}" stroke="${s('AF')}" stroke-width="1.5"/>
            <path d="M116 20 L160 22 L188 40 L176 62 L136 60 L118 44 Z" fill="${f('AS')}" stroke="${s('AS')}" stroke-width="1.5"/>
            <path d="M152 80 L186 86 L192 104 L162 114 L144 102 Z" fill="${f('AU')}" stroke="${s('AU')}" stroke-width="1.5"/>
            ${markers}`;
  }

  function statBarSvg(x, y, w, h, value, maxVal, accent) {
    const filled = Math.min(1, Math.max(0, (Number(value) || 0) / (Number(maxVal) || 100)));
    const r = h / 2;
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${accent}" opacity="0.18"/>
            <rect x="${x}" y="${y}" width="${Math.max(h, w * filled)}" height="${h}" rx="${r}" fill="${accent}" opacity="0.9"/>`;
  }

  function cornerOrnament(tx, ty, sx, sy, color) {
    return `<g transform="translate(${tx},${ty}) scale(${sx},${sy})">
      <path d="M 0,0 L 36,0 L 36,5 L 5,5 L 5,36 L 0,36 Z" fill="${color}" opacity="0.88"/>
      <rect x="32" y="32" width="7" height="7" fill="${color}" opacity="0.65"/>
      <rect x="22" y="5" width="5" height="5" fill="${color}" opacity="0.45"/>
    </g>`;
  }

  function slotContent(data, key, fallback = {}) {
    return (data.slot_content || {})[key] || fallback;
  }

  function templateParts(template) {
    const parts = Array.isArray(template?.parts) ? template.parts.filter(Boolean) : [];
    if (parts.length) return parts.slice().sort((a, b) => Number(a?.sort_order || 100) - Number(b?.sort_order || 100));
    if (template?.asset_url) return [{ slot_name: 'base_frame', asset_url: template.asset_url, asset_type: 'template', sort_order: 0 }];
    return [];
  }

  function baseFramePart(template, fallbackUrl) {
    const parts = templateParts(template);
    const base = parts.find((p) => (p.slot_name || 'base_frame') === 'base_frame');
    if (base?.asset_url) return base;
    if (template?.asset_url) return { slot_name: 'base_frame', asset_url: template.asset_url, asset_type: 'template', sort_order: 0 };
    return { slot_name: 'base_frame', asset_url: fallbackUrl, asset_type: 'template', sort_order: 0 };
  }

  function slotBox(side, slotName) {
    return { x: 0, y: 0, w: CARD_W, h: CARD_H };
  }

  function htmlPartLayers(template, side) {
    return templateParts(template).map((part) => {
      return `<img class="wx-asset-layer slot-${esc(part.slot_name || 'base_frame')}"
                   src="${esc(part.asset_url || '')}" alt=""
                   style="left:0;top:0;width:100%;height:100%;z-index:0" data-slot="${esc(part.slot_name || 'base_frame')}">`;
    }).join('');
  }

  function svgPartLayers(template, side) {
    return templateParts(template).map((part) => {
      return `<image href="${esc(part.asset_url || '')}" x="0" y="0" width="${CARD_W}" height="${CARD_H}" preserveAspectRatio="none"/>`;
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

  function frontSvg(data, template, imageHref) {
    const t = getTheme(data.theme_class);
    const artHref = imageHref || data.image_url || data.primary_card_image_url || data.original_image_url || '';
    const speciesName = data.species_name || 'Unknown';
    const scientificName = data.scientific_name || '';
    const cardNum = esc(String(data.card_number || data.dex_id || ''));
    const rarityText = String(data.rarity || 'Common').toUpperCase();
    const typeLabel = String(data.type_label || data.kingdom || '').toUpperCase();
    const filledDots = rarityFilledCount(data.rarity);
    const namePlate = slotContent(data, 'name_plate', { title: speciesName, subtitle: scientificName });
    const displayName = esc(namePlate.title || speciesName);
    const nameFontSize = displayName.length > 32 ? 20 : displayName.length > 24 ? 24 : displayName.length > 18 ? 28 : displayName.length > 12 ? 33 : 38;
    const abilities = (data.abilities || []).slice(0, 3);
    const habitatLines = chunkText(data.habitat_text || '', 48, 2);
    const hp = Number(data.hp ?? data.stats?.hp) || 0;
    const atk = Number(data.atk ?? data.stats?.attack ?? data.stats?.atk) || 0;
    const def = Number(data.def ?? data.stats?.defence ?? data.stats?.def) || 0;
    const spd = Number(data.spd ?? data.stats?.speed ?? data.stats?.spd) || 0;

    return `<svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
<defs>
  <linearGradient id="fg-bg" x1="0.15" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${t.bg3}"/>
    <stop offset="45%" stop-color="${t.bg2}"/>
    <stop offset="100%" stop-color="${t.bg1}"/>
  </linearGradient>
  <linearGradient id="fg-hdr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="rgba(0,0,0,0.60)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.05)"/>
  </linearGradient>
  <linearGradient id="fg-photo-bottom" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="rgba(0,0,0,0)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.55)"/>
  </linearGradient>
  <linearGradient id="fg-ftr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="rgba(0,0,0,0.05)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.65)"/>
  </linearGradient>
  <clipPath id="fg-photo"><rect x="28" y="90" width="694" height="380" rx="14"/></clipPath>
  <clipPath id="fg-card"><rect width="${CARD_W}" height="${CARD_H}" rx="22"/></clipPath>
</defs>
<g clip-path="url(#fg-card)">
  <rect width="${CARD_W}" height="${CARD_H}" fill="url(#fg-bg)"/>

  <!-- Subtle diagonal texture lines -->
  <g opacity="0.035" stroke="${t.accent}" stroke-width="1">
    ${Array.from({length: 20}, (_, i) => `<line x1="${i * 80 - 400}" y1="0" x2="${i * 80}" y2="${CARD_H}"/>`).join('')}
  </g>

  <!-- Outer ornate border -->
  <rect x="5" y="5" width="${CARD_W - 10}" height="${CARD_H - 10}" rx="18" fill="none" stroke="${t.accent}" stroke-width="3.5"/>
  <!-- Inner accent border -->
  <rect x="13" y="13" width="${CARD_W - 26}" height="${CARD_H - 26}" rx="12" fill="none" stroke="${t.accent2}" stroke-width="1" opacity="0.45"/>

  <!-- Corner ornaments -->
  ${cornerOrnament(18, 18, 1, 1, t.accent2)}
  ${cornerOrnament(CARD_W - 18, 18, -1, 1, t.accent2)}
  ${cornerOrnament(18, CARD_H - 18, 1, -1, t.accent2)}
  ${cornerOrnament(CARD_W - 18, CARD_H - 18, -1, -1, t.accent2)}

  <!-- Header strip -->
  <rect x="6" y="6" width="${CARD_W - 12}" height="80" rx="17 17 0 0" fill="url(#fg-hdr)"/>
  <line x1="22" y1="86" x2="${CARD_W - 22}" y2="86" stroke="${t.accent}" stroke-width="1.5" opacity="0.65"/>

  <!-- WILDEX wordmark -->
  <text x="36" y="53" font-size="10" font-family="Segoe UI,sans-serif" font-weight="900"
        fill="${t.accent}" letter-spacing="5">WILDEX</text>

  <!-- Rarity label + dots centered in header -->
  <text x="${CARD_W / 2}" y="38" text-anchor="middle" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.accent2}" letter-spacing="4" opacity="0.9">${rarityText}</text>
  ${[0,1,2,3,4].map(i =>
    `<circle cx="${CARD_W/2 - 52 + i * 26}" cy="62" r="8"
       fill="${i < filledDots ? t.accent : 'none'}" stroke="${t.accent2}" stroke-width="2" opacity="0.9"/>`
  ).join('')}

  <!-- Card number -->
  <text x="${CARD_W - 34}" y="56" text-anchor="end" font-size="26" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}" opacity="0.95">${cardNum}</text>

  <!-- Kingdom type badge pill -->
  <rect x="${CARD_W / 2 - 72}" y="70" width="144" height="20" rx="10" fill="${t.accent}" opacity="0.9"/>
  <text x="${CARD_W / 2}" y="84" text-anchor="middle" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.bg1}" letter-spacing="3">${esc(typeLabel)}</text>

  <!-- Photo zone -->
  <rect x="26" y="88" width="698" height="384" rx="16" fill="rgba(0,0,0,0.42)"/>
  ${artHref ? `<image href="${esc(artHref)}" x="28" y="90" width="694" height="380"
      preserveAspectRatio="xMidYMid slice" clip-path="url(#fg-photo)"/>` : ''}
  <!-- Photo vignette gradient bottom -->
  <rect x="28" y="360" width="694" height="110" rx="0 0 14 14" fill="url(#fg-photo-bottom)"/>
  <!-- Photo border -->
  <rect x="26" y="88" width="698" height="384" rx="16" fill="none" stroke="${t.accent}" stroke-width="2.5" opacity="0.85"/>

  <!-- Diamond divider -->
  <g transform="translate(${CARD_W / 2},498)">
    <line x1="-290" y1="0" x2="-16" y2="0" stroke="${t.accent}" stroke-width="1.5" opacity="0.55"/>
    <polygon points="0,-9 9,0 0,9 -9,0" fill="${t.accent}" opacity="0.88"/>
    <line x1="16" y1="0" x2="290" y2="0" stroke="${t.accent}" stroke-width="1.5" opacity="0.55"/>
  </g>

  <!-- Species name -->
  <text x="${CARD_W / 2}" y="540" text-anchor="middle" font-size="${nameFontSize}"
        font-family="Segoe UI,sans-serif" font-weight="800" fill="${t.text}">${displayName}</text>
  <!-- Scientific name -->
  <text x="${CARD_W / 2}" y="566" text-anchor="middle" font-size="16"
        font-family="Georgia,serif" font-style="italic" fill="${t.accent2}">${esc(scientificName)}</text>

  <!-- Thin divider -->
  <line x1="38" y1="582" x2="${CARD_W - 38}" y2="582" stroke="${t.divider}" stroke-width="1"/>

  <!-- Stats section (y 592–700) -->
  <!-- HP row -->
  <text x="46" y="610" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="2">HP</text>
  ${statBarSvg(46, 616, 282, 10, hp, 100, t.accent)}
  <text x="336" y="628" text-anchor="end" font-size="14" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${hp}</text>

  <!-- ATK row -->
  <text x="402" y="610" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="2">ATK</text>
  ${statBarSvg(402, 616, 282, 10, atk, 100, t.accent)}
  <text x="692" y="628" text-anchor="end" font-size="14" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${atk}</text>

  <!-- DEF row -->
  <text x="46" y="654" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="2">DEF</text>
  ${statBarSvg(46, 660, 282, 10, def, 100, t.accent)}
  <text x="336" y="672" text-anchor="end" font-size="14" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${def}</text>

  <!-- SPD row -->
  <text x="402" y="654" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="2">SPD</text>
  ${statBarSvg(402, 660, 282, 10, spd, 100, t.accent)}
  <text x="692" y="672" text-anchor="end" font-size="14" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${spd}</text>

  <!-- Divider -->
  <line x1="38" y1="690" x2="${CARD_W - 38}" y2="690" stroke="${t.divider}" stroke-width="1"/>

  <!-- Abilities section (y 698–800) -->
  <text x="46" y="710" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="3">ABILITIES</text>
  ${abilities.map((ab, i) => {
    const title = typeof ab === 'string' ? ab : (ab?.name || '');
    const desc = typeof ab === 'object' ? (ab?.effect || '') : '';
    const y0 = 724 + i * 42;
    return `<polygon points="44,${y0} 54,${y0 + 7} 44,${y0 + 14}" fill="${t.accent}" opacity="0.82"/>
    <text x="62" y="${y0 + 11}" font-size="15" font-family="Segoe UI,sans-serif" font-weight="700"
          fill="${t.text}">${esc(title)}</text>
    ${desc ? `<text x="62" y="${y0 + 27}" font-size="11" font-family="Segoe UI,sans-serif"
          fill="${t.textMuted}">${esc(String(desc).slice(0, 60))}</text>` : ''}`;
  }).join('')}

  <!-- Divider -->
  <line x1="38" y1="852" x2="${CARD_W - 38}" y2="852" stroke="${t.divider}" stroke-width="1"/>

  <!-- Biome badge + habitat text row (852–930) -->
  <rect x="44" y="862" width="${Math.max(60, String(data.biome || '').length * 9 + 20)}" height="22" rx="11"
        fill="${t.panel}" stroke="${t.accent}" stroke-width="1" opacity="0.88"/>
  <text x="54" y="877" font-size="11" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.accent2}">${esc(data.biome || '')}</text>

  ${habitatLines.map((line, i) =>
    `<text x="44" y="${896 + i * 20}" font-size="12" font-family="Segoe UI,sans-serif"
           fill="${t.textMuted}">${esc(line)}</text>`).join('')}

  <!-- Mini map (right side of lower area) -->
  <g transform="translate(${CARD_W - 228},856)">
    <rect width="204" height="124" rx="11" fill="${t.bg1}" stroke="${t.accent}" stroke-width="1.5" opacity="0.85"/>
    <svg viewBox="0 0 200 120" width="200" height="120" x="2" y="2">${mapInnerSvg(data)}</svg>
  </g>

  <!-- Footer strip -->
  <rect x="6" y="948" width="${CARD_W - 12}" height="${CARD_H - 954}" rx="0 0 18 18" fill="url(#fg-ftr)"/>
  <line x1="22" y1="950" x2="${CARD_W - 22}" y2="950" stroke="${t.accent}" stroke-width="1" opacity="0.45"/>

  <!-- Footer text -->
  <text x="44" y="972" font-size="9" font-family="Segoe UI,sans-serif" fill="${t.textMuted}" letter-spacing="2" opacity="0.7">DISCOVERED</text>
  <text x="44" y="990" font-size="12" font-family="Segoe UI,sans-serif" font-weight="600" fill="${t.text}">${esc(formatDiscoveredText(data))}</text>

  <text x="${CARD_W - 44}" y="972" text-anchor="end" font-size="9" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}" letter-spacing="2" opacity="0.7">BIOME BONUS</text>
  <text x="${CARD_W - 44}" y="990" text-anchor="end" font-size="12" font-family="Segoe UI,sans-serif"
        font-weight="600" fill="${t.accent2}">${esc(data.biome_bonus || '')}</text>

  <text x="${CARD_W / 2}" y="1018" text-anchor="middle" font-size="9" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}" letter-spacing="4" opacity="0.5">WILDEX · FIELD RECORD</text>
</g>
</svg>`;
  }

  function backSvg(data, template, imageHref, qrHref) {
    const t = getTheme(data.theme_class);
    const mediaHref = imageHref || data.image_url || data.primary_card_image_url || data.original_image_url || '';
    const qrImageHref = qrHref || data.qr_url || '';
    const speciesName = data.species_name || 'Unknown';
    const scientificName = data.scientific_name || '';
    const cardNum = esc(String(data.card_number || data.dex_id || ''));
    const filledDots = rarityFilledCount(data.rarity);
    const displayName = esc(speciesName);
    const nameFontSize = displayName.length > 30 ? 18 : displayName.length > 22 ? 22 : displayName.length > 16 ? 26 : displayName.length > 12 ? 28 : 32;

    const aboutLines = chunkText(data.info_text || '', 36, 6);
    const dietLines = chunkText(data.diet_text || '', 38, 3);
    const habitatLine = String(data.habitat_text || '').slice(0, 50);
    const quoteLines = chunkText(data.fact_text || '', 44, 2);
    const discoveredText = formatDiscoveredText(data);

    const THUMB_X = CARD_W - 226;
    const THUMB_Y = 90;
    const THUMB_W = 200;
    const THUMB_H = 220;

    return `<svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
<defs>
  <linearGradient id="bg-bg" x1="0.15" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${t.bg3}"/>
    <stop offset="45%" stop-color="${t.bg2}"/>
    <stop offset="100%" stop-color="${t.bg1}"/>
  </linearGradient>
  <linearGradient id="bg-hdr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="rgba(0,0,0,0.60)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.05)"/>
  </linearGradient>
  <linearGradient id="bg-ftr" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="rgba(0,0,0,0.05)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.68)"/>
  </linearGradient>
  <clipPath id="bg-thumb"><rect x="${THUMB_X}" y="${THUMB_Y}" width="${THUMB_W}" height="${THUMB_H}" rx="12"/></clipPath>
  <clipPath id="bg-card"><rect width="${CARD_W}" height="${CARD_H}" rx="22"/></clipPath>
</defs>
<g clip-path="url(#bg-card)">
  <rect width="${CARD_W}" height="${CARD_H}" fill="url(#bg-bg)"/>

  <g opacity="0.035" stroke="${t.accent}" stroke-width="1">
    ${Array.from({length: 20}, (_, i) => `<line x1="${i * 80 - 400}" y1="0" x2="${i * 80}" y2="${CARD_H}"/>`).join('')}
  </g>

  <rect x="5" y="5" width="${CARD_W - 10}" height="${CARD_H - 10}" rx="18" fill="none" stroke="${t.accent}" stroke-width="3.5"/>
  <rect x="13" y="13" width="${CARD_W - 26}" height="${CARD_H - 26}" rx="12" fill="none" stroke="${t.accent2}" stroke-width="1" opacity="0.45"/>

  ${cornerOrnament(18, 18, 1, 1, t.accent2)}
  ${cornerOrnament(CARD_W - 18, 18, -1, 1, t.accent2)}
  ${cornerOrnament(18, CARD_H - 18, 1, -1, t.accent2)}
  ${cornerOrnament(CARD_W - 18, CARD_H - 18, -1, -1, t.accent2)}

  <!-- Header -->
  <rect x="6" y="6" width="${CARD_W - 12}" height="80" rx="17 17 0 0" fill="url(#bg-hdr)"/>
  <line x1="22" y1="86" x2="${CARD_W - 22}" y2="86" stroke="${t.accent}" stroke-width="1.5" opacity="0.65"/>

  <text x="36" y="46" font-size="${nameFontSize}" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${displayName}</text>
  <text x="36" y="72" font-size="14" font-family="Georgia,serif" font-style="italic"
        fill="${t.accent2}">${esc(scientificName)}</text>
  <text x="${CARD_W - 34}" y="56" text-anchor="end" font-size="26" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}" opacity="0.9">${cardNum}</text>

  <!-- Photo thumbnail (top-right) -->
  <rect x="${THUMB_X - 2}" y="${THUMB_Y - 2}" width="${THUMB_W + 4}" height="${THUMB_H + 4}" rx="14"
        fill="rgba(0,0,0,0.45)"/>
  ${mediaHref ? `<image href="${esc(mediaHref)}" x="${THUMB_X}" y="${THUMB_Y}" width="${THUMB_W}" height="${THUMB_H}"
      preserveAspectRatio="xMidYMid slice" clip-path="url(#bg-thumb)"/>` : ''}
  <rect x="${THUMB_X - 2}" y="${THUMB_Y - 2}" width="${THUMB_W + 4}" height="${THUMB_H + 4}" rx="14"
        fill="none" stroke="${t.accent}" stroke-width="2" opacity="0.82"/>

  <!-- About section -->
  <text x="36" y="108" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="3">ABOUT</text>
  <line x1="36" y1="114" x2="${THUMB_X - 24}" y2="114" stroke="${t.divider}" stroke-width="1"/>
  ${aboutLines.map((line, i) =>
    `<text x="36" y="${130 + i * 22}" font-size="13" font-family="Segoe UI,sans-serif"
           fill="${t.text}" opacity="0.88">${esc(line)}</text>`).join('')}

  <!-- Divider -->
  <line x1="36" y1="328" x2="${CARD_W - 36}" y2="328" stroke="${t.divider}" stroke-width="1"/>

  <!-- Diet + Habitat columns (y 336–440) -->
  <text x="36" y="350" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="3">DIET</text>
  ${dietLines.map((line, i) =>
    `<text x="36" y="${366 + i * 20}" font-size="13" font-family="Segoe UI,sans-serif"
           fill="${t.text}" opacity="0.85">${esc(line)}</text>`).join('')}

  <text x="${CARD_W / 2 + 16}" y="350" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.accent2}" letter-spacing="3">HABITAT</text>
  <text x="${CARD_W / 2 + 16}" y="370" font-size="13" font-family="Segoe UI,sans-serif"
        fill="${t.text}" opacity="0.85">${esc(habitatLine)}</text>

  <!-- Length row -->
  <text x="36" y="428" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="3">LENGTH</text>
  <text x="36" y="448" font-size="14" font-family="Segoe UI,sans-serif"
        font-weight="600" fill="${t.text}">${esc(data.length_text || 'Varies by individual')}</text>

  <!-- Divider -->
  <line x1="36" y1="464" x2="${CARD_W - 36}" y2="464" stroke="${t.divider}" stroke-width="1"/>

  <!-- Strength box (y 472–548) -->
  <rect x="36" y="472" width="316" height="72" rx="11" fill="${t.panel}" stroke="${t.accent}" stroke-width="1" opacity="0.92"/>
  <text x="52" y="492" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="2">STRENGTH</text>
  <text x="52" y="510" font-size="15" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.text}">${esc(data.strength_name || '')}</text>
  <text x="52" y="528" font-size="11" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}">${esc(String(data.strength_effect || '').slice(0, 44))}</text>

  <!-- Weakness box -->
  <rect x="${CARD_W - 352}" y="472" width="316" height="72" rx="11" fill="${t.panel}" stroke="${t.accent}" stroke-width="1" opacity="0.92"/>
  <text x="${CARD_W - 336}" y="492" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.accent2}" letter-spacing="2">WEAKNESS</text>
  <text x="${CARD_W - 336}" y="510" font-size="15" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.text}">${esc(data.weakness_name || '')}</text>
  <text x="${CARD_W - 336}" y="528" font-size="11" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}">${esc(String(data.weakness_effect || '').slice(0, 44))}</text>

  <!-- Divider -->
  <line x1="36" y1="556" x2="${CARD_W - 36}" y2="556" stroke="${t.divider}" stroke-width="1"/>

  <!-- Stats column (y 564–720) -->
  <text x="36" y="576" font-size="10" font-family="Segoe UI,sans-serif" font-weight="800"
        fill="${t.accent2}" letter-spacing="3">STATS</text>
  ${(() => {
    const hpVal = Number(data.hp ?? data.stats?.hp) || 0;
    const atkVal = Number(data.atk ?? data.stats?.attack ?? data.stats?.atk) || 0;
    const defVal = Number(data.def ?? data.stats?.defence ?? data.stats?.def) || 0;
    const spdVal = Number(data.spd ?? data.stats?.speed ?? data.stats?.spd) || 0;
    return [['HP', hpVal], ['ATK', atkVal], ['DEF', defVal], ['SPD', spdVal]].map(([label, val], i) =>
      `<text x="36" y="${594 + i * 32}" font-size="10" font-family="Segoe UI,sans-serif"
             font-weight="800" fill="${t.textMuted}" letter-spacing="2">${label}</text>
      ${statBarSvg(80, 582 + i * 32, 172, 9, val, 100, t.accent)}
      <text x="260" y="${594 + i * 32}" font-size="13" font-family="Segoe UI,sans-serif"
             font-weight="700" fill="${t.text}">${val}</text>`
    ).join('');
  })()}

  <!-- Threat / Aggression badges -->
  <rect x="36" y="726" width="230" height="24" rx="12" fill="${t.panel}" stroke="${t.accent}" stroke-width="1" opacity="0.9"/>
  <text x="50" y="742" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.textMuted}">THREAT</text>
  <text x="118" y="742" font-size="12" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${esc(data.threat_level || 'Low')}</text>

  <rect x="282" y="726" width="230" height="24" rx="12" fill="${t.panel}" stroke="${t.accent}" stroke-width="1" opacity="0.9"/>
  <text x="296" y="742" font-size="10" font-family="Segoe UI,sans-serif"
        font-weight="700" fill="${t.textMuted}">AGGRESSION</text>
  <text x="395" y="742" font-size="12" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.text}">${esc(data.aggression || 'Low')}</text>

  <!-- Range map (right side, y 564–740) -->
  <g transform="translate(${CARD_W - 220},564)">
    <rect width="200" height="174" rx="12" fill="${t.bg1}" stroke="${t.accent}" stroke-width="1.8" opacity="0.88"/>
    <svg viewBox="0 0 200 120" width="196" height="120" x="2" y="8">${mapInnerSvg(data)}</svg>
    <text x="100" y="160" text-anchor="middle" font-size="9" font-family="Segoe UI,sans-serif"
          fill="${t.textMuted}" letter-spacing="2">RANGE MAP</text>
  </g>

  <!-- Divider -->
  <line x1="36" y1="762" x2="${CARD_W - 36}" y2="762" stroke="${t.divider}" stroke-width="1"/>

  <!-- Fact / Quote (y 770–836) -->
  <text x="${CARD_W / 2}" y="786" text-anchor="middle" font-size="22" font-family="Georgia,serif"
        font-style="italic" fill="${t.accent2}" opacity="0.8">&ldquo;</text>
  ${quoteLines.map((line, i) =>
    `<text x="${CARD_W / 2}" y="${806 + i * 24}" text-anchor="middle" font-size="13"
           font-family="Georgia,serif" font-style="italic" fill="${t.text}" opacity="0.85">${esc(line)}</text>`
  ).join('')}
  <text x="${CARD_W / 2}" y="${quoteLines.length > 1 ? 856 : 832}" text-anchor="middle" font-size="22"
        font-family="Georgia,serif" font-style="italic" fill="${t.accent2}" opacity="0.8">&rdquo;</text>

  <!-- Footer divider -->
  <line x1="22" y1="872" x2="${CARD_W - 22}" y2="872" stroke="${t.accent}" stroke-width="1.5" opacity="0.5"/>
  <rect x="6" y="872" width="${CARD_W - 12}" height="${CARD_H - 878}" rx="0 0 18 18" fill="url(#bg-ftr)"/>

  <!-- Rarity dots (bottom left) -->
  ${[0,1,2,3,4].map(i =>
    `<circle cx="${40 + i * 26}" cy="910" r="9"
       fill="${i < filledDots ? t.accent : 'none'}" stroke="${t.accent2}" stroke-width="2" opacity="0.9"/>`
  ).join('')}

  <!-- Type + biome (center footer) -->
  <text x="${CARD_W / 2}" y="902" text-anchor="middle" font-size="12" font-family="Segoe UI,sans-serif"
        font-weight="800" fill="${t.accent}" letter-spacing="3">${esc((data.type_label || '').toUpperCase())}</text>
  <text x="${CARD_W / 2}" y="920" text-anchor="middle" font-size="11" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}">${esc(data.biome || '')}</text>

  <!-- Discovered -->
  <text x="40" y="945" font-size="9" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}" letter-spacing="1" opacity="0.75">DISCOVERED</text>
  <text x="40" y="962" font-size="12" font-family="Segoe UI,sans-serif"
        font-weight="600" fill="${t.text}">${esc(discoveredText)}</text>

  <!-- QR code -->
  ${qrImageHref ? `<image href="${esc(qrImageHref)}" x="${CARD_W - 116}" y="886" width="90" height="90"/>
    <rect x="${CARD_W - 118}" y="884" width="94" height="94" rx="8" fill="none"
          stroke="${t.accent}" stroke-width="1.5" opacity="0.7"/>` : ''}

  <text x="${CARD_W / 2}" y="1020" text-anchor="middle" font-size="9" font-family="Segoe UI,sans-serif"
        fill="${t.textMuted}" letter-spacing="4" opacity="0.45">WILDEX · FIELD RECORD</text>
</g>
</svg>`;
  }

  function buildCard(target, data) {
    if (!target) return null;
    try {
      if (!data) throw new Error('Card data missing');
      const frontMarkup = frontSvg(data, data.front_template, data.image_url || '');
      const backMarkup = backSvg(data, data.back_template, data.image_url || '', data.qr_url || '');
      target.innerHTML = `
        <div class="wx-card-shell">
          <div class="wx-flip-card">
            <div class="wx-flip-inner">
              <div class="wx-face front ${esc(data.theme_class || '')}">${frontMarkup}</div>
              <div class="wx-face back ${esc(data.theme_class || '')}">${backMarkup}</div>
            </div>
          </div>
        </div>`;
      target.__wxData = data;
      if (!data.image_url) {
        console.warn('WildEx card render: no image_url', { dexId: data.dex_id, species: data.species_name });
      }
    } catch (err) {
      console.error('WildEx card render failed', { err, data });
      target.innerHTML = `<div class="wx-render-error" role="alert">
        <strong>Card preview unavailable</strong>
        <span>${esc(err?.message || 'Unknown render failure')}</span>
        <code>species: ${esc(data?.species_name || 'Unknown')}</code>
      </div>`;
      target.__wxData = data || null;
    }
    return target;
  }

  function flip(target) {
    const card = target.querySelector('.wx-flip-card');
    if (card) card.classList.toggle('flipped');
  }

  function printNode(node) {
    const frame = window.open('', '_blank', 'width=900,height=1300');
    if (!frame) return;
    frame.document.write(`<!doctype html><html><head><title>Print Card</title>
      <style>body{margin:0;display:grid;place-items:center;background:#111}svg{width:75mm;height:auto;display:block}</style>
      </head><body>${node.innerHTML}</body></html>`);
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
    const imageHref = data.image_url ? await assetToDataUrl(data.image_url) : '';
    const qrHref = side === 'back' && data.qr_url ? await assetToDataUrl(data.qr_url) : '';
    const svgMarkup = side === 'front'
      ? frontSvg(data, data.front_template, imageHref)
      : backSvg(data, data.back_template, imageHref, qrHref);
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
    const imageHref = data.image_url ? await assetToDataUrl(data.image_url) : '';
    const qrHref = side === 'back' && data.qr_url ? await assetToDataUrl(data.qr_url) : '';
    const svgMarkup = side === 'front'
      ? frontSvg(data, data.front_template, imageHref)
      : backSvg(data, data.back_template, imageHref, qrHref);
    const temp = document.createElement('div');
    temp.innerHTML = svgMarkup.trim();
    return svgToPngBlob(temp.firstElementChild);
  }

  function sampleCards() {
    const noTemplate = () => ({
      front_template: { name: 'naturalist-front-v1', version: '1.0.0', parts: [] },
      back_template: { name: 'naturalist-back-v1', version: '1.0.0', parts: [] },
    });
    return [
      {
        species_name: 'Ring-tailed Dragon', scientific_name: 'Ctenophorus caudicinctus',
        common_name: 'Ring-tailed Dragon', dex_id: 'AU-REP-DRG-017', card_number: '017',
        rarity: 'Rare', threat_level: 'Medium', aggression: 'Medium',
        length_text: '8–10 inches (20–25 cm)', habitat_text: 'Rocky terrain of arid Australian outback',
        diet_text: 'Insects and small invertebrates',
        info_text: 'The Ring-tailed Dragon is a small, spiny agamid lizard found across the rocky arid zones of Australia. Its banded tail is used to confuse predators and signal rivals.',
        fact_text: 'Can wag its banded tail to mimic a scurrying insect, distracting approaching predators.',
        image_url: '', sound_url: '',
        hp: 48, atk: 42, def: 58, spd: 64,
        type_label: 'Reptile', biome: 'Rocky Desert', biome_bonus: '+20% defence in arid zones',
        strength_name: 'Desert Terrain', strength_effect: '+20% defence in arid zones',
        weakness_name: 'Cold Rain', weakness_effect: 'Reduced mobility in wet conditions',
        abilities: ['Flatten Body', 'Band-tail Decoy', 'Sun Bask'],
        environment_triggers: ['Advantage in rocky terrain', 'Vulnerable to cold rain'],
        range_mode: 'region', range_regions: ['AU'], local_markers: [{ region: 'AU', x: 79, y: 60 }],
        theme_class: 'theme-reptile', banner_text: 'DRAGON',
        slot_content: { name_plate: { title: 'Ring-tailed Dragon', subtitle: 'Ctenophorus caudicinctus' } },
        ...noTemplate(),
      },
      {
        species_name: 'Red Kangaroo', scientific_name: 'Macropus rufus',
        common_name: 'Red Kangaroo', dex_id: 'AU-MAM-MAR-018', card_number: '018',
        rarity: 'Common', threat_level: 'Medium', aggression: 'High',
        length_text: '1.0–1.6 m body length', habitat_text: 'Arid plains and open woodland',
        diet_text: 'Grasses and low vegetation',
        info_text: 'The Red Kangaroo is the largest living marsupial. It dominates the inland plains of Australia, covering long distances with efficient bounding hops and regulating heat through licking its forearms.',
        fact_text: 'Can cover long distances with energy-saving hops across arid terrain.',
        image_url: '', sound_url: '',
        hp: 75, atk: 65, def: 45, spd: 70,
        type_label: 'Mammal', biome: 'Grassland', biome_bonus: '+20% damage in arid zones',
        strength_name: 'Desert', strength_effect: '+20% damage in arid zones',
        weakness_name: 'Heavy Rain', weakness_effect: 'Reduced mobility in wet conditions',
        abilities: ['Powerful Kick', 'Hop Away'],
        environment_triggers: ['Advantage in desert terrain', 'Vulnerable in heavy rain'],
        range_mode: 'region', range_regions: ['AU'], local_markers: [{ region: 'AU', x: 102, y: 84 }],
        theme_class: 'theme-mammal', banner_text: 'PAW',
        slot_content: { name_plate: { title: 'Red Kangaroo', subtitle: 'Macropus rufus' } },
        ...noTemplate(),
      },
      {
        species_name: 'Great White Shark', scientific_name: 'Carcharodon carcharias',
        common_name: 'Great White Shark', dex_id: 'AU-FSH-SHK-003', card_number: '003',
        rarity: 'Legendary', threat_level: 'Extreme', aggression: 'High',
        length_text: '3.5–6.0 m', habitat_text: 'Coastal shelf waters and offshore marine zones',
        diet_text: 'Fish, rays, and marine mammals',
        info_text: 'The Great White Shark is an apex marine predator built for explosive speed and powerful ambush strikes from below. It detects prey through electroreception and lateral-line vibration sensing.',
        fact_text: 'Uses electroreception via the ampullae of Lorenzini to detect prey in murky water.',
        image_url: '', sound_url: '',
        hp: 84, atk: 92, def: 62, spd: 78,
        type_label: 'Marine', biome: 'Ocean Current', biome_bonus: '+20% speed in open water',
        strength_name: 'Open Water', strength_effect: '+20% speed in marine zones',
        weakness_name: 'Shallow Heat', weakness_effect: 'Reduced endurance in warm shallow water',
        abilities: ['Burst Rush', 'Ambush Bite'],
        environment_triggers: ['Advantage in marine terrain', 'Vulnerable to shallow heat'],
        range_mode: 'ocean', range_regions: ['PACIFIC', 'INDIAN', 'ATLANTIC'], local_markers: [],
        theme_class: 'theme-fish', banner_text: 'FISH',
        slot_content: { name_plate: { title: 'Great White Shark', subtitle: 'Carcharodon carcharias' } },
        ...noTemplate(),
      },
      {
        species_name: 'Bald Eagle', scientific_name: 'Haliaeetus leucocephalus',
        common_name: 'Bald Eagle', dex_id: 'NA-BRD-RAP-004', card_number: '004',
        rarity: 'Rare', threat_level: 'High', aggression: 'High',
        length_text: '70–102 cm body length', habitat_text: 'Large lakes, coasts and river systems',
        diet_text: 'Fish, birds, and carrion',
        info_text: 'The Bald Eagle patrols large waterways with exceptional eyesight and devastating diving strikes. It is the national bird of the United States and a symbol of conservation success.',
        fact_text: 'Builds some of the largest nests of any bird — up to 3 metres wide and 600 kg.',
        image_url: '', sound_url: '',
        hp: 64, atk: 74, def: 52, spd: 83,
        type_label: 'Bird', biome: 'Sky / Cliff', biome_bonus: '+20% speed in open air',
        strength_name: 'High Wind', strength_effect: '+20% scouting in elevated terrain',
        weakness_name: 'Dense Brush', weakness_effect: 'Reduced maneuvering in canopy',
        abilities: ['High Scan', 'Dive Strike'],
        environment_triggers: ['Advantage in elevated terrain', 'Vulnerable in dense brush'],
        range_mode: 'world', range_regions: ['NA'], local_markers: [{ region: 'NA', x: 34, y: 36 }],
        theme_class: 'theme-bird', banner_text: 'WING',
        slot_content: { name_plate: { title: 'Bald Eagle', subtitle: 'Haliaeetus leucocephalus' } },
        ...noTemplate(),
      },
      {
        species_name: 'Pitcher Plant', scientific_name: 'Nepenthes rafflesiana',
        common_name: 'Pitcher Plant', dex_id: 'AS-PLT-BOT-011', card_number: '011',
        rarity: 'Cryptic', threat_level: 'Low', aggression: 'Low',
        length_text: 'Pitchers to 30 cm', habitat_text: 'Humid wetlands and nutrient-poor ground',
        diet_text: 'Insects trapped in pitcher fluid',
        info_text: 'The Pitcher Plant grows ornate pitfall traps that lure insects with vivid colour, scent, and nectar secretions. Its digestive fluid slowly breaks down trapped prey to supplement poor soil nutrients.',
        fact_text: 'Digestive fluid inside the pitcher can dissolve insects and even small frogs over several days.',
        image_url: '', sound_url: '',
        hp: 42, atk: 36, def: 54, spd: 22,
        type_label: 'Plant', biome: 'Botanical Habitat', biome_bonus: '+20% resilience in native soil',
        strength_name: 'Rooted Soil', strength_effect: '+20% resilience in stable ground',
        weakness_name: 'Transplant Shock', weakness_effect: 'Reduced vitality outside native habitat',
        abilities: ['Pitfall Trap', 'Digestive Pool'],
        environment_triggers: ['Advantage in humid terrain', 'Vulnerable to transplant shock'],
        range_mode: 'world', range_regions: ['AS'], local_markers: [{ region: 'AS', x: 139, y: 48 }],
        theme_class: 'theme-plant', banner_text: 'LEAF',
        slot_content: { name_plate: { title: 'Pitcher Plant', subtitle: 'Nepenthes rafflesiana' } },
        ...noTemplate(),
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
    frontSvg,
    backSvg,
    CARD_W,
    CARD_H,
  };
})();
