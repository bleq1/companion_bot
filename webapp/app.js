const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  const isDark = tg.colorScheme === 'dark';
  if (isDark) {
    document.body.classList.add('tg-theme-dark');
    tg.setHeaderColor('#1A1612');
    tg.setBackgroundColor('#1A1612');
  } else {
    tg.setHeaderColor('#F8F1E9');
    tg.setBackgroundColor('#F8F1E9');
  }
}

// ===== API =====
// Укажите публичный адрес API бота (ngrok / VPS).
// Пример: https://xxxx.ngrok-free.app
const API_BASE = (window.COMPANION_API || localStorage.getItem('companion_api') || '').replace(/\/$/, '');

const PLACEHOLDER = 'placeholder.png';

// Fallback, если API недоступен
const FALLBACK = [
  {
    id: 1, name: "Матвей", age: 20,
    interests: ["IT", "программирование", "технологии", "стартапы"],
    soft_skills: ["активное слушание", "структурность", "эмпатия", "честная обратная связь"],
    about: "Разбираюсь в айтишке и всём, что с ней связано. Могу помочь с выбором направления, выгоранием в IT, поиском работы или просто поговорить на одном языке.",
    username: "Matveytgtg",
    photo_url: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=600&h=600&fit=crop"
  },
  {
    id: 2, name: "Егор", age: 21,
    interests: ["Витебск", "город", "помощь приезжим", "ориентирование"],
    soft_skills: ["дружелюбие", "практичность", "открытость", "умение объяснять просто"],
    about: "Хорошо знаю Витебск. Могу помочь приезжим: куда сходить, как добраться, где лучше жить, что посмотреть.",
    username: "nqupio", photo_url: ""
  },
  {
    id: 3, name: "Клим", age: 21,
    interests: ["общение", "поддержка", "жизненные ситуации", "саморазвитие"],
    soft_skills: ["терпение", "непредвзятость", "тёплый тон", "умение держать паузу"],
    about: "Просто человек, который умеет слушать. Можно прийти с любой темой — от «просто плохо» до разбора конкретной ситуации.",
    username: "kilklim", photo_url: ""
  },
  {
    id: 4, name: "Полина", age: 20,
    interests: ["поддержка женщин", "развод", "отношения", "восстановление"],
    soft_skills: ["эмпатия", "жизненный опыт", "мягкая сила", "честность"],
    about: "Могу поддержать женщин после развода. Сама проходила через это несколько раз — удачно и без разрушительных последствий.",
    username: "pv_0_20",
    photo_url: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=600&h=600&fit=crop"
  }
];

let COMPANIONS = [...FALLBACK];
let currentView = 'home';
let searchQuery = '';

const viewHome = document.getElementById('view-home');
const viewProfile = document.getElementById('view-profile');
const viewAbout = document.getElementById('view-about');
const companionsList = document.getElementById('companions-list');
const companionsCount = document.getElementById('companions-count');
const profileContent = document.getElementById('profile-content');
const searchInput = document.getElementById('search-input');

function resolvePhoto(url) {
  if (!url) return PLACEHOLDER;
  if (url.startsWith('http')) return url;
  if (url.startsWith('/') && API_BASE) return API_BASE + url;
  return url || PLACEHOLDER;
}

function photoOf(c) {
  return resolvePhoto(c.photo_url);
}

function matchesSearch(c, q) {
  if (!q) return true;
  const hay = [c.name, c.about, ...(c.interests || []), ...(c.soft_skills || [])].join(' ').toLowerCase();
  return q.split(/\s+/).every(word => hay.includes(word));
}

function filteredCompanions() {
  const q = searchQuery.trim().toLowerCase();
  return COMPANIONS.filter(c => matchesSearch(c, q));
}

function renderCards() {
  const list = filteredCompanions();
  companionsCount.textContent = list.length;
  if (list.length === 0) {
    companionsList.innerHTML = `<div class="empty-search">Никого не найдено по запросу «${searchQuery}»</div>`;
    return;
  }
  companionsList.innerHTML = list.map(c => `
    <article class="card" data-id="${c.id}">
      <div class="card-inner">
        <img class="card-photo" src="${photoOf(c)}" alt="${c.name}" loading="lazy"
             onerror="this.src='${PLACEHOLDER}'" />
        <div class="card-info">
          <div class="card-name">${c.name}</div>
          <div class="card-meta">${c.age} лет · ${(c.interests && c.interests[0]) || ''}</div>
          <div class="card-interests">
            ${(c.interests || []).slice(0, 3).map(i => `<span class="tag">${i}</span>`).join('')}
          </div>
        </div>
      </div>
    </article>
  `).join('');

  document.querySelectorAll('.card').forEach(card => {
    card.addEventListener('click', () => openProfile(parseInt(card.dataset.id)));
  });
}

function openProfile(id) {
  const c = COMPANIONS.find(x => x.id === id);
  if (!c) return;

  profileContent.innerHTML = `
    <div class="profile-photo-wrap">
      <img class="profile-photo" src="${photoOf(c)}" alt="${c.name}" onerror="this.src='${PLACEHOLDER}'" />
      <div class="profile-photo-overlay"></div>
    </div>
    <div class="profile-header">
      <h1 class="profile-name">${c.name}</h1>
      <div class="profile-age">${c.age} лет</div>
    </div>
    <p class="profile-about">${c.about || ''}</p>
    <div class="profile-section">
      <h3>Интересы</h3>
      <div class="interests-list">
        ${(c.interests || []).map(i => `<span class="interest-tag">${i}</span>`).join('')}
      </div>
    </div>
    <div class="profile-section">
      <h3>Софт-скиллы</h3>
      <div class="skills-list">
        ${(c.soft_skills || []).map(s => `<span class="skill-tag">${s}</span>`).join('')}
      </div>
    </div>
    <div class="actions">
      <button class="btn btn-primary" id="btn-chat">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        Написать ${c.name}
      </button>
    </div>
  `;
  document.getElementById('btn-chat').addEventListener('click', () => startChat(c));
  showView('profile');
}

function startChat(companion) {
  const link = `https://t.me/${companion.username}`;
  if (tg) {
    tg.openTelegramLink(link);
    tg.HapticFeedback?.impactOccurred('medium');
  } else {
    window.open(link, '_blank');
  }
}

function showView(name) {
  currentView = name;
  viewHome.classList.toggle('active', name === 'home');
  viewProfile.classList.toggle('active', name === 'profile');
  viewAbout.classList.toggle('active', name === 'about');
  document.getElementById('main').scrollTop = 0;
}

document.getElementById('btn-back').addEventListener('click', () => showView('home'));
document.getElementById('btn-back-about').addEventListener('click', () => showView('home'));
document.getElementById('btn-about').addEventListener('click', () => showView('about'));

if (searchInput) {
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value;
    renderCards();
  });
}

async function loadCompanions() {
  if (!API_BASE) {
    console.warn('API_BASE не задан — показываем fallback');
    COMPANIONS = [...FALLBACK];
    renderCards();
    return;
  }
  try {
    const res = await fetch(API_BASE + '/api/companions', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (Array.isArray(data) && data.length) {
      COMPANIONS = data;
    }
  } catch (e) {
    console.warn('Не удалось загрузить с API, fallback', e);
    COMPANIONS = [...FALLBACK];
  }
  renderCards();
}

loadCompanions();

if (tg) {
  tg.BackButton.onClick(() => {
    if (currentView !== 'home') {
      showView('home');
      tg.BackButton.hide();
    }
  });
  const originalShow = showView;
  showView = function(name) {
    originalShow(name);
    if (name === 'home') tg.BackButton.hide();
    else tg.BackButton.show();
  };
}
