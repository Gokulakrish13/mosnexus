// Render all tasks with pagination
function renderTasks(filteredTasks = null) {
    const tasksToRender = filteredTasks || tasks;
    
    const todoTasks = tasksToRender.filter(task => task.status === 'todo');
    const progressTasks = tasksToRender.filter(task => task.status === 'progress');
    const doneTasks = tasksToRender.filter(task => task.status === 'done');
    
    const todoPages = Math.ceil(todoTasks.length / TASKS_PER_PAGE) || 1;
    const progressPages = Math.ceil(progressTasks.length / TASKS_PER_PAGE) || 1;
    const donePages = Math.ceil(doneTasks.length / TASKS_PER_PAGE) || 1;
    
    document.querySelector('.total-pages[data-status="todo"]').textContent = todoPages;
    document.querySelector('.total-pages[data-status="progress"]').textContent = progressPages;
    document.querySelector('.total-pages[data-status="done"]').textContent = donePages;
    
    // Ensure current page is valid
    currentPages.todo = Math.min(currentPages.todo, todoPages);
    currentPages.progress = Math.min(currentPages.progress, progressPages);
    currentPages.done = Math.min(currentPages.done, donePages);
    
    document.querySelector('.current-page[data-status="todo"]').textContent = currentPages.todo;
    document.querySelector('.current-page[data-status="progress"]').textContent = currentPages.progress;
    document.querySelector('.current-page[data-status="done"]').textContent = currentPages.done;
    
    document.querySelector('.prev-btn[data-status="todo"]').disabled = currentPages.todo <= 1;
    document.querySelector('.next-btn[data-status="todo"]').disabled = currentPages.todo >= todoPages;
    document.querySelector('.prev-btn[data-status="progress"]').disabled = currentPages.progress <= 1;
    document.querySelector('.next-btn[data-status="progress"]').disabled = currentPages.progress >= progressPages;
    document.querySelector('.prev-btn[data-status="done"]').disabled = currentPages.done <= 1;
    document.querySelector('.next-btn[data-status="done"]').disabled = currentPages.done >= donePages;
    
    todoTasksEl.innerHTML = '';
    progressTasksEl.innerHTML = '';
    doneTasksEl.innerHTML = '';
    
    // Render paginated tasks for each column
    const todoStart = (currentPages.todo - 1) * TASKS_PER_PAGE;
    const todoEnd = todoStart + TASKS_PER_PAGE;
    todoTasks.slice(todoStart, todoEnd).forEach(task => {
        todoTasksEl.appendChild(createTaskElement(task));
    });
    
    const progressStart = (currentPages.progress - 1) * TASKS_PER_PAGE;
    const progressEnd = progressStart + TASKS_PER_PAGE;
    progressTasks.slice(progressStart, progressEnd).forEach(task => {
        progressTasksEl.appendChild(createTaskElement(task));
    });
    
    const doneStart = (currentPages.done - 1) * TASKS_PER_PAGE;
    const doneEnd = doneStart + TASKS_PER_PAGE;
    doneTasks.slice(doneStart, doneEnd).forEach(task => {
        doneTasksEl.appendChild(createTaskElement(task));
    });
    
    // Apply compact view if enabled
    if (compactView) {
        applyCompactView();
    }
    
    updateTaskCounts(tasksToRender);
    
    // If in month view mode, also update the month view
    if (viewMode === 'month') {
        renderMonthView(tasksToRender);
    }
}

// Render month-wise view
function renderMonthView(filteredTasks = null) {
    const tasksToRender = filteredTasks || tasks;
    const monthContainer = document.getElementById('month-container');
    monthContainer.innerHTML = '';
    
    const tasksByMonth = {};
    tasksToRender.forEach(task => {
        if (task.dueDate) {
            const date = new Date(task.dueDate);
            const monthYear = `${date.getFullYear()}-${(date.getMonth() + 1).toString().padStart(2, '0')}`;
            if (!tasksByMonth[monthYear]) {
                tasksByMonth[monthYear] = [];
            }
            tasksByMonth[monthYear].push(task);
        }
    });
    
    const sortedMonths = Object.keys(tasksByMonth).sort().reverse();
    
    // Pagination for months
    const monthsPerPage = 3;
    const totalMonthPages = Math.ceil(sortedMonths.length / monthsPerPage) || 1;
    
    document.getElementById('total-month-pages').textContent = totalMonthPages;
    currentPages.month = Math.min(currentPages.month, totalMonthPages);
    document.getElementById('current-month-page').textContent = currentPages.month;
    
    document.getElementById('prev-month-page').disabled = currentPages.month <= 1;
    document.getElementById('next-month-page').disabled = currentPages.month >= totalMonthPages;
    
    const monthStart = (currentPages.month - 1) * monthsPerPage;
    const monthEnd = monthStart + monthsPerPage;
    const monthsToDisplay = sortedMonths.slice(monthStart, monthEnd);
    
    monthsToDisplay.forEach(monthYear => {
        const [year, month] = monthYear.split('-');
        const date = new Date(parseInt(year), parseInt(month) - 1, 1);
        const monthName = date.toLocaleString('default', { month: 'long', year: 'numeric' });
        
        const monthSection = document.createElement('div');
        monthSection.classList.add('month-section');
        
        // Create month header
        const monthHeader = document.createElement('div');
        monthHeader.classList.add('month-header');
        monthHeader.innerHTML = `
            <span>${monthName} (${tasksByMonth[monthYear].length} tasks)</span>
            <span class="collapse-icon">▼</span>
        `;
        
        const monthTasks = document.createElement('div');
        monthTasks.classList.add('month-tasks');
        
        // Sort tasks by due date
        const sortedTasks = tasksByMonth[monthYear].sort((a, b) => new Date(a.dueDate) - new Date(b.dueDate));
        
        sortedTasks.forEach(task => {
            monthTasks.appendChild(createTaskElement(task));
        });
        
        // Add click handler for expanding/collapsing
        monthHeader.addEventListener('click', () => {
            monthHeader.classList.toggle('collapsed');
            monthTasks.classList.toggle('collapsed');
        });
        
        monthSection.appendChild(monthHeader);
        monthSection.appendChild(monthTasks);
        monthContainer.appendChild(monthSection);
    });
    
    // If no months, show a message
    if (monthsToDisplay.length === 0) {
        const noTasksMessage = document.createElement('div');
        noTasksMessage.style.textAlign = 'center';
        noTasksMessage.style.margin = '40px 0';
        noTasksMessage.style.color = '#999';
        noTasksMessage.textContent = 'No tasks with due dates found';
        monthContainer.appendChild(noTasksMessage);
    }
}
