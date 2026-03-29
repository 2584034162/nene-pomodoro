const { createApp, ref, onMounted, computed, watch } = Vue;

// 自动判断环境：如果是本地开发(localhost/127.0.0.1)，使用本地后端；否则使用生产环境后端
// 这里吧后端部署到了render上面，因此是下面这样
const PROD_API_URL = 'https://nene-pomodoro.onrender.com';
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
            checkins: {
                today: 0
            },
            pomodoro: {
                total_minutes: 0
            },
            tasks: {
                completed_today: 0,
                completion_rate: 0
            },
            score: {
                discipline: 0
            }
        });

        // 表单数据
        const loginForm = ref({ username: '', password: '' });
        const registerForm = ref({ username: '', password: '' });
        const newTask = ref({
            title: '',
            description: '',
            target: {
                type: 'count',
                value: 1
            }
        });
        const showCreateTaskModal = ref(false);

        // 番茄钟状态
        const pomodoroTime = ref(25 * 60);
        const customDuration = ref(25); // 自定义时长(分钟)
        const pomodoroActive = ref(false);
        const pomodoroStatus = ref('idle'); // idle, work, break
        const selectedTaskId = ref(''); // 选中的任务ID
        let timerInterval = null;

        // AI记账状态
        const aiConfig = ref({
            assistant_name: 'NeNe记账助理',
            personality: '温柔、耐心、像朋友一样自然聊天',
            api_provider: 'custom',
            api_url: '',
            api_key: '',
            api_model: 'gpt-4o-mini'
        });
        const modelOptions = ref([]);
        const providerOptions = ref([
            { label: '自定义', value: 'custom', baseUrl: '' },
            { label: 'OpenAI', value: 'openai', baseUrl: 'https://api.openai.com/v1' },
            { label: 'Gemini', value: 'gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai' },
            { label: 'Claude', value: 'claude', baseUrl: 'https://api.anthropic.com/v1' }
        ]);
        const chatMessages = ref([]);
        const chatInput = ref('');
        const chatLoading = ref(false);
        const accountingRecords = ref([]);
        const accountingSummary = ref({
            income: 0,
            expense: 0,
            balance: 0
        });

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
                await fetchData();
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
            chatMessages.value = [];
            accountingRecords.value = [];
            modelOptions.value = [];
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
                newTask.value = {
                    title: '',
                    description: '',
                    target: {
                        type: 'count',
                        value: 1
                    }
                };
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

        // AI记账
        const normalizeApiUrlWithV1 = (url) => {
            let text = String(url || '').trim();
            if (!text) return '';
            text = text.replace(/\/+$/, '');
            if (text.endsWith('/chat/completions')) return text;
            if (text.includes('/v1/') || text.endsWith('/v1')) return text;
            return `${text}/v1`;
        };

        const inferProviderFromUrl = (url) => {
            const target = String(url || '').trim().toLowerCase();
            if (!target) return 'custom';
            const hit = providerOptions.value.find(p => p.value !== 'custom' && target.startsWith(p.baseUrl.toLowerCase()));
            return hit ? hit.value : 'custom';
        };

        const applyProviderPreset = () => {
            const selected = providerOptions.value.find(p => p.value === aiConfig.value.api_provider);
            if (!selected || selected.value === 'custom') return;
            aiConfig.value.api_url = selected.baseUrl;
        };

        const onApiUrlBlur = () => {
            aiConfig.value.api_url = normalizeApiUrlWithV1(aiConfig.value.api_url);
            aiConfig.value.api_provider = inferProviderFromUrl(aiConfig.value.api_url);
        };

        const fetchAiConfig = async () => {
            if (!isLoggedIn.value) return;
            try {
                const res = await axios.get(`${API_URL}/api/ai-accounting/config`);
                aiConfig.value = {
                    ...aiConfig.value,
                    ...res.data
                };
                aiConfig.value.api_provider = inferProviderFromUrl(aiConfig.value.api_url);
            } catch (error) {
                console.error('加载AI配置失败', error);
            }
        };

        const fetchAvailableModels = async () => {
            if (!aiConfig.value.api_url) {
                alert('请先填写 API URL');
                return;
            }
            try {
                const normalizedUrl = normalizeApiUrlWithV1(aiConfig.value.api_url);
                aiConfig.value.api_url = normalizedUrl;
                const res = await axios.get(`${API_URL}/api/ai-accounting/models`, {
                    params: {
                        api_url: normalizedUrl,
                        api_key: aiConfig.value.api_key
                    }
                });
                modelOptions.value = res.data.models || [];
                if (!modelOptions.value.length) {
                    alert(res.data.msg || '未获取到可用模型');
                    return;
                }
                if (!modelOptions.value.includes(aiConfig.value.api_model)) {
                    aiConfig.value.api_model = modelOptions.value[0];
                }
            } catch (error) {
                alert(error.response?.data?.msg || '拉取模型失败');
            }
        };

        const saveAiConfig = async () => {
            try {
                const payload = {
                    ...aiConfig.value,
                    api_url: normalizeApiUrlWithV1(aiConfig.value.api_url)
                };
                const res = await axios.put(`${API_URL}/api/ai-accounting/config`, payload);
                aiConfig.value = {
                    ...aiConfig.value,
                    ...res.data.config
                };
                aiConfig.value.api_provider = inferProviderFromUrl(aiConfig.value.api_url);
                alert('AI配置已保存');
            } catch (error) {
                alert(error.response?.data?.msg || '保存配置失败');
            }
        };

        const fetchAccountingRecords = async () => {
            if (!isLoggedIn.value) return;
            try {
                const res = await axios.get(`${API_URL}/api/accounting/records`);
                accountingRecords.value = res.data.records || [];
                accountingSummary.value = res.data.summary || {
                    income: 0,
                    expense: 0,
                    balance: 0
                };
            } catch (error) {
                console.error('获取记账记录失败', error);
            }
        };

        const sendAccountingMessage = async () => {
            const message = chatInput.value.trim();
            if (!message || chatLoading.value) return;

            const userMsg = { role: 'user', content: message };
            chatMessages.value.push(userMsg);
            chatInput.value = '';
            chatLoading.value = true;

            try {
                const history = chatMessages.value.slice(0, -1);
                const payload = { message, history };
                const res = await axios.post(`${API_URL}/api/ai-accounting/chat`, payload);
                const isError = !!res.data.is_error;
                chatMessages.value.push({
                    role: 'assistant',
                    content: res.data.assistant_reply || '已收到',
                    isError,
                    retryPayload: isError ? payload : null
                });
                accountingRecords.value = res.data.records || accountingRecords.value;
                await fetchAccountingRecords();
            } catch (error) {
                const payload = { message, history: chatMessages.value.slice(0, -1) };
                chatMessages.value.push({
                    role: 'assistant',
                    content: error.response?.data?.msg || '发送失败，请检查配置后重试。',
                    isError: true,
                    retryPayload: payload
                });
            } finally {
                chatLoading.value = false;
            }
        };

        const regenerateAccountingMessage = async (msg, idx) => {
            if (!msg || !msg.retryPayload || chatLoading.value) return;

            chatLoading.value = true;
            try {
                const res = await axios.post(`${API_URL}/api/ai-accounting/chat`, msg.retryPayload);
                const isError = !!res.data.is_error;
                chatMessages.value[idx] = {
                    role: 'assistant',
                    content: res.data.assistant_reply || '已收到',
                    isError,
                    retryPayload: isError ? msg.retryPayload : null
                };
                accountingRecords.value = res.data.records || accountingRecords.value;
                await fetchAccountingRecords();
            } catch (error) {
                chatMessages.value[idx] = {
                    role: 'assistant',
                    content: error.response?.data?.msg || '重新生成失败，请稍后再试。',
                    isError: true,
                    retryPayload: msg.retryPayload
                };
            } finally {
                chatLoading.value = false;
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
            alert('专注时间结束!');

            if (pomodoroStatus.value === 'work') {
                try {
                    await axios.post(`${API_URL}/api/checkin`, {
                        type: 'pomodoro',
                        duration: customDuration.value,
                        task_id: selectedTaskId.value || null
                    });
                    fetchData();
                } catch (e) {
                    console.error(e);
                }

                pomodoroStatus.value = 'break';
                pomodoroTime.value = 5 * 60;
                if (confirm('开始休息吗?')) startPomodoro();
            } else {
                pomodoroStatus.value = 'work';
                pomodoroTime.value = customDuration.value * 60;
            }
        };

        // 监听选中的任务
        watch(selectedTaskId, (newId) => {
            if (!newId) return;
            const task = tasks.value.find(t => String(t.id) === String(newId));
            if (task && task.target?.type === 'time') {
                customDuration.value = task.target.value;
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

            chartInstance = new Chart(ctx, {
                type: 'radar',
                data: {
                    labels: ['专注力', '持久力', '活跃度', '完成率', '连续打卡'],
                    datasets: [{
                        label: '我的自律能力',
                        data: [
                            stats.value.score.discipline,
                            Math.min(stats.value.pomodoro.total_minutes, 100),
                            Math.min(stats.value.checkins.today * 10, 100),
                            stats.value.tasks.completion_rate,
                            Math.min((stats.value.checkins.streak_days || 0) * 10, 100)
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
        onMounted(async () => {
            if (isLoggedIn.value) {
                currentView.value = 'dashboard';
                await fetchData();
            }
        });

        // 监听视图变化
        watch(currentView, async (newVal) => {
            if (newVal === 'dashboard') {
                setTimeout(renderChart, 100);
            }
            if (newVal === 'accounting') {
                await fetchAiConfig();
                await fetchAccountingRecords();
                if (aiConfig.value.api_url) {
                    await fetchAvailableModels();
                }
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
            aiConfig,
            providerOptions,
            chatMessages,
            chatInput,
            chatLoading,
            accountingRecords,
            accountingSummary,
            modelOptions,
            login,
            register,
            logout,
            createTask,
            deleteTask,
            checkInTask,
            formatTime,
            startPomodoro,
            pausePomodoro,
            resetPomodoro,
            fetchAvailableModels,
            applyProviderPreset,
            onApiUrlBlur,
            saveAiConfig,
            sendAccountingMessage,
            regenerateAccountingMessage
        };
    }
}).mount('#app');
