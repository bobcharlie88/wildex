(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const CARD_W = 744;
  const CARD_H = 1039;

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

  function frontSvg(data, templateHref, imageHref) {
    const infoY = [0, 80, 160, 250, 340];
    const infoRows = [
      ['Common Name', data.common_name || data.species_name],
      ['Scientific Name', data.scientific_name],
      ['Length', data.length_text],
      ['Habitat', data.habitat_text],
      ['Diet', data.diet_text],
    ];
    const infoContent = infoRows.map((row, idx) => {
      const lines = chunkText(row[1], idx === 3 ? 28 : 22, idx === 3 ? 3 : 2);
      return `
        <text x="82" y="${255 + infoY[idx]}" font-size="18" font-weight="700" fill="#5a3d2a" letter-spacing="1.2">${esc(row[0].toUpperCase())}</text>
        ${textLines(lines, 82, 282 + infoY[idx], 22, 22, 'fill="#2c1d13" font-family="Georgia, serif"')}
      `;
    }).join('');
    const infoLines = chunkText(data.info_text, 52, 6);
    const factLines = chunkText(data.fact_text, 56, 2);
    return `
      <svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
        <defs>
          <clipPath id="photoClip"><rect x="380" y="260" width="292" height="370" rx="14"></rect></clipPath>
        </defs>
        ${templateHref ? `<image href="${templateHref}" x="0" y="0" width="${CARD_W}" height="${CARD_H}" preserveAspectRatio="none"></image>` : ''}
        <text x="99" y="102" text-anchor="middle" font-size="54" font-family="Georgia, serif" font-weight="700" fill="#f7eedb">${esc(data.card_number)}</text>
        <text x="208" y="101" font-size="42" font-weight="800" fill="#f7eedb" letter-spacing="5">WILDEX</text>
        <text x="630" y="100" text-anchor="middle" font-size="28" font-weight="700" fill="#f7eedb">${esc(data.banner_text)}</text>
        <text x="372" y="176" text-anchor="middle" font-size="54" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${esc(data.species_name)}</text>
        <text x="372" y="218" text-anchor="middle" font-size="28" font-family="Georgia, serif" font-style="italic" fill="#5a3d2a">${esc(data.scientific_name)}</text>
        ${infoContent}
        ${imageHref ? `<image href="${imageHref}" x="380" y="260" width="292" height="370" preserveAspectRatio="xMidYMid slice" clip-path="url(#photoClip)"></image>` : ''}
        <text x="148" y="696" text-anchor="middle" font-size="28" font-weight="800" fill="#f7eedb" letter-spacing="2">INFO</text>
        ${textLines(infoLines, 64, 748, 28, 24, 'fill="#2c1d13" font-family="Georgia, serif"')}
        <text x="88" y="972" font-size="26" font-weight="800" fill="#f7eedb" letter-spacing="2">FACT</text>
        ${textLines(factLines, 188, 971, 22, 20, 'fill="#f7eedb" font-family="Georgia, serif" font-style="italic"')}
      </svg>`;
  }

  function backSvg(data, templateHref) {
    const abilities = (data.abilities || []).slice(0, 3);
    const triggers = (data.environment_triggers || []).slice(0, 2);
    return `
      <svg xmlns="${SVG_NS}" viewBox="0 0 ${CARD_W} ${CARD_H}" width="${CARD_W}" height="${CARD_H}">
        ${templateHref ? `<image href="${templateHref}" x="0" y="0" width="${CARD_W}" height="${CARD_H}" preserveAspectRatio="none"></image>` : ''}
        <text x="99" y="102" text-anchor="middle" font-size="54" font-family="Georgia, serif" font-weight="700" fill="#f7eedb">${esc(data.card_number)}</text>
        <text x="208" y="100" font-size="30" font-weight="800" fill="#f7eedb" letter-spacing="2">${esc(data.dex_id || 'WILDEX')}</text>
        <text x="650" y="101" text-anchor="middle" font-size="20" font-weight="700" fill="#f7eedb">${esc(data.banner_text)}</text>
        <text x="372" y="176" text-anchor="middle" font-size="54" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${esc(data.species_name)}</text>
        <text x="372" y="218" text-anchor="middle" font-size="28" font-family="Georgia, serif" font-style="italic" fill="#5a3d2a">${esc(data.scientific_name)}</text>
        <text x="78" y="280" font-size="20" font-weight="800" fill="#5a3d2a">RARITY</text>
        <text x="210" y="280" font-size="22" font-weight="700" fill="#2c1d13">${esc(data.rarity)}</text>
        <text x="78" y="314" font-size="20" font-weight="800" fill="#5a3d2a">THREAT LEVEL</text>
        <text x="220" y="314" font-size="22" font-weight="700" fill="#2c1d13">${esc(data.threat_level)}</text>
        <text x="78" y="348" font-size="20" font-weight="800" fill="#5a3d2a">AGGRESSION</text>
        <text x="210" y="348" font-size="22" font-weight="700" fill="#2c1d13">${esc(data.aggression)}</text>
        <g transform="translate(347 284)">
          <g transform="scale(1.52 1.28)">
            ${mapInnerSvg(data)}
          </g>
        </g>
        <text x="78" y="414" font-size="20" font-weight="800" fill="#5a3d2a">STRENGTH</text>
        <text x="78" y="448" font-size="34" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${esc(data.strength_name)}</text>
        <text x="78" y="474" font-size="22" fill="#2c1d13">${esc(data.strength_effect)}</text>
        <text x="78" y="530" font-size="20" font-weight="800" fill="#5a3d2a">WEAKNESS</text>
        <text x="78" y="564" font-size="34" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${esc(data.weakness_name)}</text>
        <text x="78" y="590" font-size="22" fill="#2c1d13">${esc(data.weakness_effect)}</text>
        <text x="78" y="648" font-size="24" font-weight="800" fill="#5a3d2a">HP</text><text x="224" y="648" text-anchor="end" font-size="42" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${data.hp}</text>
        <text x="78" y="696" font-size="24" font-weight="800" fill="#5a3d2a">ATK</text><text x="224" y="696" text-anchor="end" font-size="42" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${data.atk}</text>
        <text x="78" y="744" font-size="24" font-weight="800" fill="#5a3d2a">DEF</text><text x="224" y="744" text-anchor="end" font-size="42" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${data.def}</text>
        <text x="78" y="792" font-size="24" font-weight="800" fill="#5a3d2a">SPD</text><text x="224" y="792" text-anchor="end" font-size="42" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${data.spd}</text>
        <text x="308" y="648" font-size="20" font-weight="800" fill="#5a3d2a">TYPE</text>
        <text x="308" y="678" font-size="32" font-family="Georgia, serif" font-weight="700" fill="#2c1d13">${esc(data.type_label)}</text>
        <text x="308" y="708" font-size="20" fill="#2c1d13">${esc(data.biome_bonus)}</text>
        <text x="308" y="764" font-size="20" font-weight="800" fill="#5a3d2a">ABILITIES</text>
        ${abilities.map((line, idx) => `<text x="320" y="${798 + idx * 26}" font-size="22" fill="#2c1d13">&#8226; ${esc(line)}</text>`).join('')}
        <text x="78" y="862" font-size="20" font-weight="800" fill="#5a3d2a">ENVIRONMENT TRIGGERS</text>
        ${triggers.map((line, idx) => `<text x="78" y="${892 + idx * 22}" font-size="22" fill="#2c1d13">${esc(line)}</text>`).join('')}
        ${data.sound_url ? '<text x="372" y="966" text-anchor="middle" font-size="36" font-family="Georgia, serif" font-weight="700" fill="#f7eedb">Play Call</text>' : ''}
        <text x="76" y="1007" font-size="15" fill="#f7eedb">Rarity: ${esc(data.rarity)}</text>
        <text x="290" y="1007" font-size="15" fill="#f7eedb">Threat Level: ${esc(data.threat_level)}</text>
        <text x="532" y="1007" font-size="15" fill="#f7eedb">Aggression: ${esc(data.aggression)}</text>
      </svg>`;
  }

  function mountSvgFace(target, svgMarkup, themeClass, sideClass) {
    target.className = ['wx-face', sideClass, themeClass].filter(Boolean).join(' ');
    target.innerHTML = svgMarkup;
  }

  function buildCard(target, data) {
    const frontTemplateUrl = data.front_template?.asset_url || '';
    const backTemplateUrl = data.back_template?.asset_url || '';

    target.innerHTML = `
      <div class="wx-card-shell">
        <div class="wx-flip-card">
          <div class="wx-flip-inner">
            <div class="wx-face front ${esc(data.theme_class)}"></div>
            <div class="wx-face back ${esc(data.theme_class)}"></div>
          </div>
        </div>
      </div>`;

    const front = target.querySelector('.wx-face.front');
    const back = target.querySelector('.wx-face.back');
    mountSvgFace(front, frontSvg(data, frontTemplateUrl, data.image_url || ''), data.theme_class, 'front');
    mountSvgFace(back, backSvg(data, backTemplateUrl), data.theme_class, 'back');
    target.__wxData = data;

    Promise.allSettled([
      assetToDataUrl(frontTemplateUrl),
      assetToDataUrl(backTemplateUrl),
      data.image_url ? assetToDataUrl(data.image_url) : Promise.resolve(''),
    ]).then(([frontTemplate, backTemplate, photo]) => {
      if (target.__wxData !== data) return;
      const frontHref = frontTemplate.status === 'fulfilled' ? (frontTemplate.value || frontTemplateUrl) : frontTemplateUrl;
      const backHref = backTemplate.status === 'fulfilled' ? (backTemplate.value || backTemplateUrl) : backTemplateUrl;
      const photoHref = photo.status === 'fulfilled' ? (photo.value || data.image_url || '') : (data.image_url || '');
      if (!photoHref) {
        console.warn('WildEx card render missing image', { dexId: data.dex_id, species: data.species_name });
      }
      mountSvgFace(front, frontSvg(data, frontHref, photoHref), data.theme_class, 'front');
      mountSvgFace(back, backSvg(data, backHref), data.theme_class, 'back');
    }).catch((err) => {
      console.warn('WildEx card renderer asset fallback', err);
    });

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
    const templateUrl = (side === 'front' ? data.front_template?.asset_url : data.back_template?.asset_url) || '';
    const templateHref = await assetToDataUrl(templateUrl);
    const imageHref = side === 'front' ? await assetToDataUrl(data.image_url || '') : '';
    const svgMarkup = side === 'front' ? frontSvg(data, templateHref, imageHref) : backSvg(data, templateHref);
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
    const templateUrl = (side === 'front' ? data.front_template?.asset_url : data.back_template?.asset_url) || '';
    const templateHref = await assetToDataUrl(templateUrl);
    const imageHref = side === 'front' ? await assetToDataUrl(data.image_url || '') : '';
    const svgMarkup = side === 'front' ? frontSvg(data, templateHref, imageHref) : backSvg(data, templateHref);
    const temp = document.createElement('div');
    temp.innerHTML = svgMarkup.trim();
    return svgToPngBlob(temp.firstElementChild);
  }

  function sampleCards() {
    const makeTemplates = (kingdom) => ({
      front_template: {
        name: `${kingdom}-front-master`,
        version: '1.0.0',
        asset_url: `/static/card_templates/${kingdom}/front-v1.svg`,
      },
      back_template: {
        name: `${kingdom}-back-master`,
        version: '1.0.0',
        asset_url: `/static/card_templates/${kingdom}/back-v1.svg`,
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
