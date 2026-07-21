/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      colors: {
        surface: '#f9f9f9',
        'surface-dim': '#dadada',
        'surface-bright': '#f9f9f9',
        'surface-container-lowest': '#ffffff',
        'surface-container-low': '#f3f3f3',
        'surface-container': '#eeeeee',
        'surface-container-high': '#e8e8e8',
        'surface-container-highest': '#e2e2e2',
        'surface-variant': '#e2e2e2',
        'on-surface': '#1a1c1c',
        'on-surface-variant': '#444748',
        'inverse-surface': '#2f3131',
        'inverse-on-surface': '#f0f1f1',
        outline: '#747878',
        'outline-variant': '#c4c7c7',
        primary: '#000000',
        'on-primary': '#ffffff',
        'primary-container': '#1c1b1b',
        'on-primary-container': '#858383',
        secondary: '#5e5e5e',
        'on-secondary': '#ffffff',
        'secondary-container': '#e3e2e2',
        'on-secondary-container': '#646464',
        background: '#fafafa',
        'on-background': '#1a1c1c',
        error: '#ba1a1a',
        'error-container': '#ffdad6',
        'on-error-container': '#93000a'
      },
      borderRadius: {
        DEFAULT: '0.125rem',
        lg: '0.25rem',
        xl: '0.5rem',
        full: '0.75rem'
      },
      spacing: {
        xs: '4px',
        sm: '12px',
        base: '8px',
        md: '24px',
        lg: '48px',
        xl: '80px',
        gutter: '20px',
        margin: '24px'
      },
      fontSize: {
        'headline-lg': ['32px', { lineHeight: '1.2', letterSpacing: '-0.02em', fontWeight: '500' }],
        'headline-lg-mobile': ['24px', { lineHeight: '1.2', letterSpacing: '-0.01em', fontWeight: '500' }],
        'headline-md': ['20px', { lineHeight: '1.4', fontWeight: '500' }],
        'body-lg': ['16px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '1.6', fontWeight: '400' }],
        'label-md': ['12px', { lineHeight: '1', letterSpacing: '0.02em', fontWeight: '500' }]
      },
      fontFamily: {
        sans: ['Inter', 'Helvetica Neue', 'Helvetica', 'Arial', 'sans-serif']
      }
    }
  },
  plugins: [require('@tailwindcss/forms')]
}
