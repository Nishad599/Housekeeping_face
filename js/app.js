/* ============================================
   Face Attendance System - Core JS
   ============================================ */

const API = {
    token: localStorage.getItem('token'),
    role: localStorage.getItem('role'),
    userName: localStorage.getItem('userName'),

    headers() {
        const h = { 'Content-Type': 'application/json' };
        if (this.token) h['Authorization'] = `Bearer ${this.token}`;
        return h;
    },

    async get(url) {
        const res = await fetch(url, { headers: this.headers() });
        if (res.status === 401) { this.logout(); return null; }
        return res.json();
    },

    async post(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            headers: this.headers(),
            body: JSON.stringify(data),
        });
        return res.json();
    },

    async postForm(url, formData) {
        const h = {};
        if (this.token) h['Authorization'] = `Bearer ${this.token}`;
        const res = await fetch(url, {
            method: 'POST',
            headers: h,
            body: formData,
        });
        return res.json();
    },

    async put(url, data) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: this.headers(),
            body: JSON.stringify(data),
        });
        return res.json();
    },

    async delete(url) {
        const res = await fetch(url, {
            method: 'DELETE',
            headers: this.headers(),
        });
        return res.json();
    },

    async login(username, password) {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
            credentials: 'same-origin',
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Login failed');
        }
        const data = await res.json();
        this.token = data.access_token;
        this.role = data.role;
        this.userName = data.full_name;

        // Save to localStorage for API client
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('role', data.role);
        localStorage.setItem('userName', data.full_name);

        // Cookie is now set server-side as HttpOnly
        return data;
    },

    logout() {
        this.token = null;
        this.role = null;
        localStorage.removeItem('token');
        localStorage.removeItem('role');
        localStorage.removeItem('userName');

        // Clear HttpOnly cookie via server endpoint
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
            .finally(() => { window.location.href = '/login'; });
    },

    isLoggedIn() {
        return !!this.token;
    },

    isAdmin() {
        return this.role === 'admin';
    },
};

// Utility functions
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showAlert(container, msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `alert alert-${type}`;
    el.textContent = msg;
    container.prepend(el);
    setTimeout(() => el.remove(), 5000);
}

function formatTime(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

function statusBadge(status) {
    const map = {
        'Present': 'success',
        'Absent': 'danger',
        'Partial': 'warning',
        'Invalid': 'danger',
        'Weekly Off': 'info',
    };
    return `<span class="badge badge-${map[status] || 'info'}">${status}</span>`;
}

// Set active nav
function setActiveNav() {
    const path = window.location.pathname;
    $$('.sidebar-nav a').forEach(a => {
        a.classList.toggle('active', a.getAttribute('href') === path);
    });
}

document.addEventListener('DOMContentLoaded', setActiveNav);
