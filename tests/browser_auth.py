"""Use the same login page as an operator; never inject browser credentials."""
def login(page,base,token,path='/console'):
    page.goto(base+path)
    if '/login' in page.url:
        page.locator('#login-key').fill(token)
        page.locator('#login-submit').click()
        page.wait_for_url(lambda url:'/login' not in str(url))
    page.wait_for_function('window.VAFAuth && window.VAFAuth.session !== null')
