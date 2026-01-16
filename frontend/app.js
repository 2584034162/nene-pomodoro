const { createApp, ref, onMounted, computed, watch } = Vue;

// 自动判断环境：如果是本地开发(localhost/127.0.0.1)，使用本地后端；否则使用生产环境后端
// 请在部署后端后，将 'https://YOUR-RENDER-APP-NAME.onrender.com' 替换为您实际的 Render 后端 URL
const PROD_API_URL = 'https://YOUR-RENDER-APP-NAME.onrender.com';
const API_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
    ? 'http://127.0.0.1:5000' 
    : PROD_API_URL;

createApp({
    setup() {
        // 状态
        const currentView = ref('login');
        const token = ref(localStorage.getItem('token') || '');
        const username = ref(localStorage.getItem('username') || '');
        const tasks = ref([]);
        const stats = ref({
            today_checkins: 0,
            total_pomodoro_minutes: 0,
            discipline_score: 0,
            completion_rate: 0,
            current_streak: 0,
            completed_tasks_count: 0
        });
        
        // 表单数据
        const loginForm = ref({ username: '', password: '' });
        const registerForm = ref({ username: '', password: '' });
        const newTask = ref({ title: '', description: '', target_type: 'count', target_value: 1 });
        const showCreateTaskModal = ref(false);

        // 番茄钟状态
        const pomodoroTime = ref(25 * 60);
        const customDuration = ref(25); // 自定义时长(分钟)
        const pomodoroActive = ref(false);
        const pomodoroStatus = ref('idle'); // idle, work, break
        const selectedTaskId = ref(''); // 选中的任务ID
        let timerInterval = null;

        // 计算属性
        const isLoggedIn = computed(() => !!token.value);

        const groupedTasks = computed(() => {
            const groups = {};
            tasks.value.forEach(task => {
                const date = new Date(task.created_at).toLocaleDateString();
                if (!groups[date]) {
                    groups[date] = [];
                }
                groups[date].push(task);
            });
            return groups;
        });

        // Axios 拦截器
        axios.interceptors.request.use(config => {
            if (token.value) {
                config.headers.Authorization = `Bearer ${token.value}`;
            }
            return config;
        });

        // 方法
        const login = async () => {
            try {
                const res = await axios.post(`${API_URL}/auth/login`, loginForm.value);
                token.value = res.data.access_token;
                username.value = loginForm.value.username;
                localStorage.setItem('token', token.value);
                localStorage.setItem('username', username.value);
                currentView.value = 'dashboard';
                fetchData();
            } catch (error) {
                alert(error.response?.data?.msg || '登录失败');
            }
        };

        const register = async () => {
            try {
                await axios.post(`${API_URL}/auth/register`, registerForm.value);
                alert('注册成功，请登录');
                currentView.value = 'login';
            } catch (error) {
                alert(error.response?.data?.msg || '注册失败');
            }
        };

        const logout = () => {
            token.value = '';
            username.value = '';
            localStorage.removeItem('token');
            localStorage.removeItem('username');
            currentView.value = 'login';
        };

        const fetchData = async () => {
            if (!isLoggedIn.value) return;
            try {
                const [tasksRes, statsRes] = await Promise.all([
                    axios.get(`${API_URL}/api/tasks`),
                    axios.get(`${API_URL}/api/stats`)
                ]);
                tasks.value = tasksRes.data;
                stats.value = statsRes.data;
                renderChart();
            } catch (error) {
                console.error('获取数据失败', error);
                if (error.response?.status === 401) logout();
            }
        };

        const createTask = async () => {
            try {
                await axios.post(`${API_URL}/api/tasks`, newTask.value);
                showCreateTaskModal.value = false;
                newTask.value = { title: '', description: '', target_type: 'count', target_value: 1 };
                fetchData();
            } catch (error) {
                alert('创建任务失败');
            }
        };

        const deleteTask = async (id) => {
            if (!confirm('确定删除吗?')) return;
            try {
                await axios.delete(`${API_URL}/api/tasks/${id}`);
                fetchData();
            } catch (error) {
                alert('删除失败');
            }
        };

        const checkInTask = async (taskId) => {
            try {
                await axios.post(`${API_URL}/api/checkin`, {
                    type: 'task_checkin',
                    task_id: taskId
                });
                alert('打卡成功!');
                fetchData();
            } catch (error) {
                alert('打卡失败');
            }
        };

        // 番茄钟逻辑
        const formatTime = (seconds) => {
            const m = Math.floor(seconds / 60).toString().padStart(2, '0');
            const s = (seconds % 60).toString().padStart(2, '0');
            return `${m}:${s}`;
        };

        const startPomodoro = () => {
            if (pomodoroStatus.value === 'idle') pomodoroStatus.value = 'work';
            pomodoroActive.value = true;
            timerInterval = setInterval(() => {
                if (pomodoroTime.value > 0) {
                    pomodoroTime.value--;
                } else {
                    completePomodoro();
                }
            }, 1000);
        };

        const pausePomodoro = () => {
            pomodoroActive.value = false;
            clearInterval(timerInterval);
        };

        const resetPomodoro = () => {
            pausePomodoro();
            pomodoroStatus.value = 'idle';
            pomodoroTime.value = customDuration.value * 60;
        };

        const completePomodoro = async () => {
            pausePomodoro();
            // 播放提示音 (可选)
            alert('专注时间结束!');
            
            if (pomodoroStatus.value === 'work') {
                // 记录专注时间
                try {
                    await axios.post(`${API_URL}/api/checkin`, {
                        type: 'pomodoro',
                        duration: customDuration.value,
                        task_id: selectedTaskId.value || null
                    });
                    fetchData();
                } catch (e) { console.error(e); }

                pomodoroStatus.value = 'break';
                pomodoroTime.value = 5 * 60;
                if(confirm('开始休息吗?')) startPomodoro();
            } else {
                pomodoroStatus.value = 'work';
                pomodoroTime.value = customDuration.value * 60;
            }
        };

        // 监听选中的任务
        watch(selectedTaskId, (newId) => {
            if (!newId) return;
            const task = tasks.value.find(t => t.id === newId);
            if (task && task.target_type === 'time') {
                customDuration.value = task.target_value;
            }
        });

        // 监听自定义时长
        watch(customDuration, (newVal) => {
            if (pomodoroStatus.value === 'idle') {
                pomodoroTime.value = newVal * 60;
            }
        });

        // 图表
        let chartInstance = null;
        const renderChart = () => {
            const ctx = document.getElementById('radarChart');
            if (!ctx) return;
            
            if (chartInstance) chartInstance.destroy();

            // 模拟雷达图数据
            chartInstance = new Chart(ctx, {
                type: 'radar',
                data: {
                    labels: ['专注力', '持久力', '活跃度', '完成率', '连续打卡'],
                    datasets: [{
                        label: '我的自律能力',
                        data: [
                            stats.value.discipline_score, 
                            Math.min(stats.value.total_pomodoro_minutes, 100), 
                            Math.min(stats.value.today_checkins * 10, 100), 
                            stats.value.completion_rate, 
                            Math.min(stats.value.current_streak * 10, 100)
                        ],
                        fill: true,
                        backgroundColor: 'rgba(54, 162, 235, 0.2)',
                        borderColor: 'rgb(54, 162, 235)',
                        pointBackgroundColor: 'rgb(54, 162, 235)',
                        pointBorderColor: '#fff',
                        pointHoverBackgroundColor: '#fff',
                        pointHoverBorderColor: 'rgb(54, 162, 235)'
                    }]
                },
                options: {
                    elements: {
                        line: { borderWidth: 3 }
                    },
                    scales: {
                        r: {
                            angleLines: { display: false },
                            suggestedMin: 0,
                            suggestedMax: 100
                        }
                    }
                }
            });
        };

        // 生命周期
        onMounted(() => {
            if (isLoggedIn.value) {
                currentView.value = 'dashboard';
                fetchData();
            }
        });

        // 监听视图变化以重新渲染图表
        watch(currentView, (newVal) => {
            if (newVal === 'dashboard') {
                setTimeout(renderChart, 100);
            }
        });

        return {
            currentView,
            isLoggedIn,
            username,
            loginForm,
            registerForm,
            tasks,
            groupedTasks,
            stats,
            newTask,
            showCreateTaskModal,
            pomodoroTime,
            customDuration,
            pomodoroActive,
            pomodoroStatus,
            selectedTaskId,
            login,
            register,
            logout,
            createTask,
            deleteTask,
            checkInTask,
            formatTime,
            startPomodoro,
            pausePomodoro,
            resetPomodoro
        };
    }
}).mount('#app');
