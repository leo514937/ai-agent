import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';

// 从环境变量中读取真实的 API Base URL，严禁硬编码或本地 Mock JSON
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://api.local-life.com/v1';

class ApiClient {
  private instance: AxiosInstance;

  constructor() {
    this.instance = axios.create({
      baseURL: BASE_URL,
      timeout: 10000, // 10秒超时
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.initializeRequestInterceptor();
    this.initializeResponseInterceptor();
  }

  // 请求拦截器：注入全局 Token、经纬度定位等
  private initializeRequestInterceptor() {
    this.instance.interceptors.request.use(
      (config) => {
        // 1. 从本地存储或状态管理中获取用户 Token
        const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
        if (token && config.headers) {
          config.headers['Authorization'] = `Bearer ${token}`;
        }

        // 2. 从本地存储中读取地理位置定位，统一作为 Header 传给后端，实现近距离排序
        if (typeof window !== 'undefined') {
          const lat = localStorage.getItem('user_latitude');
          const lng = localStorage.getItem('user_longitude');
          if (lat && lng && config.headers) {
            config.headers['X-User-Latitude'] = lat;
            config.headers['X-User-Longitude'] = lng;
          }
        }

        return config;
      },
      (error) => Promise.reject(error)
    );
  }

  // 响应拦截器：集中做错误捕获和降级引导
  private initializeResponseInterceptor() {
    this.instance.interceptors.response.use(
      (response: AxiosResponse) => {
        const resData = response.data;
        // 契约校验：后端返回 code 200 为成功，其他均视为业务错误
        if (resData.code !== 200) {
          return Promise.reject(new Error(resData.message || '业务逻辑错误'));
        }
        return resData.data; // 直接向外层透传包含在 data 中的具体负载数据
      },
      (error) => {
        // 统一处理 HTTP 状态码错误
        if (error.response) {
          const status = error.response.status;
          switch (status) {
            case 401:
              // 未授权：清理本地登录态并重定向至登录页
              if (typeof window !== 'undefined') {
                localStorage.removeItem('auth_token');
                window.location.href = '/login';
              }
              break;
            case 403:
              console.error('权限不足，拒绝访问');
              break;
            case 404:
              console.error('请求的资源不存在');
              break;
            case 500:
              console.error('服务器内部错误，请稍后再试');
              break;
            default:
              console.error(`网络请求异常，状态码: ${status}`);
          }
        } else if (error.request) {
          // 请求已发出但未收到响应 (例如断网、网关超时)
          console.error('网络连接失败，请检查网络设置');
        } else {
          console.error(`请求初始化异常: ${error.message}`);
        }
        return Promise.reject(error);
      }
    );
  }

  // 基础请求方法封装
  public get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.get(url, config);
  }

  public post<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.post(url, data, config);
  }

  public put<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.put(url, data, config);
  }

  public delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.delete(url, config);
  }
}

export const apiClient = new ApiClient();
export default apiClient;
