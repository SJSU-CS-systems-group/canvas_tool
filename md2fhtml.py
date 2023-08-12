import markdownify
import markdown


def html2mdstr(html_str: str):
    """Converts html in string form to markdown"""
    md_str = markdownify.markdownify(html_str)
    return md_str


def html2mdlist(html_list: list):
    """Converts html as a list of strings to markdown"""
    html_str = '\n'.join(html_list)
    return html2mdstr(html_str)


def md2htmlstr(md_str: str):
    """Converts markdown in string form to html"""
    html_str = markdown.markdown(md_str)
    return html_str


def md2htmllist(md_list: list):
    """Converts markdown as a list of strings to html"""
    md_str = '\n'.join(md_list)
    return md2htmlstr(md_str)
