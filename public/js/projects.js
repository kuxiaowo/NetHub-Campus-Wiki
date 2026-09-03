const projectList = document.querySelector('#projectList');
const projectCount = document.querySelector('#projectCount');
const categoryList = document.querySelector('#categoryList');
const yearSelect = document.querySelector('#yearSelect');
const sortSelect = document.querySelector('#sortSelect');
const searchInput = document.querySelector('#searchInput');
const projectFilterToggle = document.querySelector('#projectFilterToggle');
const projectAdvancedFilters = document.querySelector('#projectAdvancedFilters');
const projectFilterCount = document.querySelector('#projectFilterCount');
const clearProjectFilters = document.querySelector('#clearProjectFilters');

const initialParams = new URLSearchParams(window.location.search);
let selectedCategory = initialParams.get('category') || '';
let debounceTimer = null;

function activeFilterCount() {
  return Number(Boolean(selectedCategory))
    + Number(Boolean(yearSelect.value))
    + Number(sortSelect.value !== 'latest');
}

function setFilterPanelOpen(isOpen) {
  projectAdvancedFilters.hidden = !isOpen;
  projectFilterToggle.setAttribute('aria-expanded', String(isOpen));
  projectFilterToggle.setAttribute('aria-label', isOpen ? '收起详细筛选' : '显示详细筛选');
  projectFilterToggle.classList.toggle('is-open', isOpen);
}

function updateFilterIndicator() {
  const count = activeFilterCount();
  projectFilterCount.hidden = count === 0;
  projectFilterCount.textContent = String(count);
  projectFilterToggle.classList.toggle('has-active-filters', count > 0);
  clearProjectFilters.disabled = count === 0;
}

/**
 * 渲染项目库中的横向项目行。
 */
function projectRow(project) {
  const projectId = encodeURIComponent(project.id);

  return `
    <a class="project-row" href="/detail.html?id=${projectId}">
      ${projectIconImage(project)}
      <div>
        <h3>${escapeHtml(project.name)}</h3>
        <div class="meta">
          <span class="badge">${escapeHtml(project.category)}</span>
          <span>${escapeHtml(project.year)}</span>
          <span>负责人：${escapeHtml(project.leader || '待确认')}</span>
          <span>成员：${escapeHtml(project.members || '待添加')}</span>
        </div>
        <p>${escapeHtml(project.description)}</p>
        ${casTags(project.cas)}
      </div>
    </a>
  `;
}

// 加载筛选元数据：分类按钮和年份下拉框。
async function loadMeta() {
  const meta = await request('/meta');
  if (!meta.categories.includes(selectedCategory)) selectedCategory = '';

  categoryList.innerHTML = [
    `<button class="category-button ${selectedCategory ? '' : 'active'}" type="button" data-category="">全部分类</button>`,
    ...meta.categories.map((category) => {
      const safeCategory = escapeHtml(category);
      const active = category === selectedCategory ? 'active' : '';
      return `<button class="category-button ${active}" type="button" data-category="${safeCategory}">${safeCategory}</button>`;
    }),
  ].join('');

  yearSelect.innerHTML = `<option value="">全部年份</option>` +
    meta.years.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`).join('');

  const initialYear = initialParams.get('year') || '';
  const initialSort = initialParams.get('sort') || 'latest';
  if ([...yearSelect.options].some((option) => option.value === initialYear)) yearSelect.value = initialYear;
  sortSelect.value = initialSort === 'popular' ? 'popular' : 'latest';
  updateFilterIndicator();
  if (activeFilterCount() > 0) setFilterPanelOpen(true);

  // 使用事件委托处理动态生成的分类按钮，避免给每个按钮单独绑定事件。
  categoryList.addEventListener('click', (event) => {
    const button = event.target.closest('.category-button');
    if (!button) return;
    selectedCategory = button.dataset.category;
    document.querySelectorAll('.category-button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    updateFilterIndicator();
    loadProjects();
  });
}

// 根据当前筛选状态查询项目列表。
async function loadProjects() {
  projectList.innerHTML = '<div class="empty">正在加载项目...</div>';
  const params = new URLSearchParams();
  if (selectedCategory) params.set('category', selectedCategory);
  if (yearSelect.value) params.set('year', yearSelect.value);
  if (searchInput.value.trim()) params.set('search', searchInput.value.trim());
  params.set('sort', sortSelect.value);

  const result = await request(`/projects?${params.toString()}`);
  projectCount.textContent = `共 ${result.data.length} 个项目`;
  projectList.innerHTML = result.data.length
    ? result.data.map(projectRow).join('')
    : '<div class="empty">没有找到符合条件的项目，换个筛选试试。</div>';
}

[yearSelect, sortSelect].forEach((el) => el.addEventListener('change', () => {
  updateFilterIndicator();
  loadProjects();
}));

projectFilterToggle.addEventListener('click', () => {
  setFilterPanelOpen(projectAdvancedFilters.hidden);
});

clearProjectFilters.addEventListener('click', () => {
  selectedCategory = '';
  yearSelect.value = '';
  sortSelect.value = 'latest';
  categoryList.querySelectorAll('.category-button').forEach((button) => {
    button.classList.toggle('active', button.dataset.category === '');
  });
  updateFilterIndicator();
  loadProjects();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !projectAdvancedFilters.hidden) {
    setFilterPanelOpen(false);
    projectFilterToggle.focus();
  }
});

// 搜索框输入频率高，使用 300ms 防抖减少无意义请求。
searchInput.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadProjects, 300);
});

loadMeta().then(loadProjects).catch((error) => {
  projectList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。请确认后端和数据库已启动。</div>`;
});
