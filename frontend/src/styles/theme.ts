import type { GlobalThemeOverrides } from 'naive-ui'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#6c5ce7',
    primaryColorHover: '#5a4bd1',
    primaryColorPressed: '#5a4bd1',
    primaryColorSuppl: '#6c5ce7',
    infoColor: '#6c5ce7',
    borderRadius: '10px',
    borderRadiusSmall: '6px',
    // borderRadiusLarge not a CommonVars key — handled via component-specific overrides
    fontFamily: `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif`,
    textColorBase: '#1a1b2e',
    textColor2: '#8b8fa8',
    borderColor: '#e6e8f0',
    dividerColor: '#e6e8f0',
    boxShadow1: '0 2px 8px rgba(0,0,0,0.06)',
    boxShadow2: '0 6px 24px rgba(0,0,0,0.09)',
    successColor: '#2ecc71',
    warningColor: '#f39c12',
    errorColor: '#e74c5e',
  },
  Message: { borderRadius: '10px' },
  Modal: { borderRadius: '20px' },
}
