import DefaultTheme from 'vitepress/theme'
import ResourceCard from './components/ResourceCard.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    // 全局注册资源卡片组件，在任意 .md 文件中可直接使用 <ResourceCard />
    app.component('ResourceCard', ResourceCard)
  },
}
