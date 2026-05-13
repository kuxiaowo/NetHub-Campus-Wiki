const projectList = document.querySelector('#projectList');
const projectCount = document.querySelector('#projectCount');
const categoryList = document.querySelector('#categoryList');
const yearSelect = document.querySelector('#yearSelect');
const sortSelect = document.querySelector('#sortSelect');
const searchInput = document.querySelector('#searchInput');

let selectedCategory = '';
let debounceTimer = null;

/**
 * 渲染项目库中的横向项目行。
 */
function projectRow(project) {
  const projectId = encodeURIComponent(project.id);

  return `
    <a class="project-row" href="/detail.html?id=${projectId}">
      <div class="project-icon">${escapeHtml(project.icon)}</div>
      <div>
        <h3>${escapeHtml(project.name)}</h3>
        <div class="meta">
          <span class="badge">${escapeHtml(project.category)}</span>
          <span>${escapeHtml(project.year)}</span>
          <span>负责人：${escapeHtml(project.leader)}</span>
          <span>成员：${escapeHtml(project.members)}</span>
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

  categoryList.innerHTML = [
    `<button class="category-button active" data-category="">全部分类</button>`,
    ...meta.categories.map((category) => {
      const safeCategory = escapeHtml(category);
      return `<button class="category-button" data-category="${safeCategory}">${safeCategory}</button>`;
    }),
  ].join('');

  yearSelect.innerHTML = `<option value="">全部年份</option>` +
    meta.years.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`).join('');

  // 使用事件委托处理动态生成的分类按钮，避免给每个按钮单独绑定事件。
  categoryList.addEventListener('click', (event) => {
    const button = event.target.closest('.category-button');
    if (!button) return;
    selectedCategory = button.dataset.category;
    document.querySelectorAll('.category-button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
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

[yearSelect, sortSelect].forEach((el) => el.addEventListener('change', loadProjects));

// 搜索框输入频率高，使用 300ms 防抖减少无意义请求。
searchInput.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadProjects, 300);
});

loadMeta().then(loadProjects).catch((error) => {
  projectList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。请确认后端和数据库已启动。</div>`;
});
