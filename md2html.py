import markdownify


def html2mdstr(html_str: str):
    """Converts html in string form to markdown"""
    md_str = markdownify.markdownify(html_str)
    return md_str


def html2mdlist(html_list: list):
    """Converts html as a list of strings to markdown"""
    html_str = ''.join(html_list)
    return html2mdstr(html_str)
