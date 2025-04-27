// 此文件用于Cloudflare Workers与Pages集成
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

/**
 * 处理请求
 * @param {Request} request
 */
async function handleRequest(request) {
  const url = new URL(request.url)
  
  // 静态文件路由 - 用Pages提供静态内容
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname.endsWith('.html') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.ico') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.jpg') ||
    url.pathname.endsWith('.jpeg') ||
    url.pathname.endsWith('.svg')
  ) {
    // 让Pages处理静态资源
    return fetch(request)
  }

  // 如果是API请求，将其重定向到后端API
  if (
    url.pathname.startsWith('/download') ||
    url.pathname.startsWith('/progress') ||
    url.pathname.startsWith('/download_file/') ||
    url.pathname.startsWith('/delete/') ||
    url.pathname.startsWith('/send_feedback')
  ) {
    // 将请求转发到后端API服务
    // 替换为您实际的后端API URL
    const apiUrl = 'https://video-downloader-api.onrender.com' + url.pathname;
    
    // 创建新的请求对象，保持原始请求的所有信息
    const modifiedRequest = new Request(apiUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: 'follow'
    });
    
    try {
      const response = await fetch(modifiedRequest);
      return response;
    } catch (error) {
      return new Response(`API请求失败: ${error.message}`, { status: 500 });
    }
  }
  
  // 主页
  if (url.pathname === '/' || url.pathname === '') {
    return fetch(request)
  }
  
  // 404页面
  return new Response('Not Found', { status: 404 })
} 