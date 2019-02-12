"""URL routes for the marXdown application."""

from typing import Dict, Callable, Optional, Tuple
from werkzeug.urls import url_parse, url_unparse, url_encode

from werkzeug.exceptions import NotFound
import jinja2
from flask_s3 import url_for as s3_url_for
from flask import Blueprint, render_template_string, request, \
    render_template, current_app, url_for

from arxiv import status
from . import render
from .services import site, index

Response = Tuple[str, int, dict]


def from_sitemap(page_path: str = '') -> Response:
    """Handle a request for ``page_path``."""
    try:
        page = site.load_page(page_path)
    except site.PageNotFound:
        raise NotFound('No such page')

    # If static files are up in S3, we want to generate static URLs for S3
    # rather than local ones.
    if current_app.config['FLASKS3_ACTIVE']:
        this_url_for = s3_url_for
    else:
        this_url_for = url_for

    # Support for response parameters in page frontmatter. This is to support
    # stubs for deleted/moved pages (ARXIVNG-1545).
    code: int = status.HTTP_200_OK
    deleted: bool = False
    headers = {}
    if 'response' in page.metadata:
        code = page.metadata['response'].get('status', status.HTTP_200_OK)
        if 'location' in page.metadata['response']:
            linker = render.get_linker(page, site.get_site_name())
            location_rel = page.metadata['response']['location']
            route, kwarg, name, anchor = linker(location_rel)
            if kwarg is None:
                location = route
            else:
                if anchor is not None:
                    location = this_url_for(route, **{kwarg: name},
                                            _anchor=anchor)
                else:
                    location = this_url_for(route, **{kwarg: name})
            headers['Location'] = location
        deleted = page.metadata['response'].get('deleted', False)
        if deleted:
            code = status.HTTP_404_NOT_FOUND

    # Page metadata (populated from the frontmatter in the markdown source) is
    # injected into the rendering context.
    context = dict(page.metadata)
    context.update({
        'page_path': page_path,
        'page': page,
        'site_name': site.get_site_name(),
        'url_for': this_url_for,
        'pagetitle': page.metadata['title']     # ARXIVNG-1697
    })
    content = render_template_string(page.content, **context)
    return content, code, headers


def search() -> Response:
    """Handle a search request."""
    q = request.args.get('q')
    limit = min(int(request.args.get('l', 20)), 50)
    page_no = int(request.args.get('p', 1))
    results = index.find(q, page_number=page_no, limit=limit) if q else None

    site_name = site.get_site_name()
    title = f"Search {site.get_site_human_short_name()}"
    context = dict(results=results, q=q, site_name=site_name, pagetitle=title)
    try:
        data = render_template(f'{site_name}/search.html', **context)
    except jinja2.exceptions.TemplateNotFound:
        data = render_template('docs/search.html', **context)
    return data, status.HTTP_200_OK, {}


def url_for_page_builder() -> Dict[str, Callable]:
    """Add a page URL builder function to the template context."""
    def url_for_page(page: int) -> str:
        """Build an URL to for a search result page."""
        rule = request.url_rule
        parts = url_parse(url_for(rule.endpoint))
        args = request.args.copy()
        args['p'] = page
        parts = parts.replace(query=url_encode(args))
        url: str = url_unparse(parts)
        return url
    return dict(url_for_page=url_for_page)


def get_blueprint(site_path: str, with_search: bool = True) -> Blueprint:
    """Generate a blueprint for this site on the fly."""
    blueprint = Blueprint(site.get_site_name(), __name__,
                          url_prefix=site.get_url_prefix(),
                          static_folder=site.get_static_path(),
                          template_folder=site.get_templates_path(),
                          static_url_path=f'{site.get_site_name()}_static')
    blueprint.route('/')(from_sitemap)
    blueprint.route('/<path:page_path>')(from_sitemap)
    if with_search:
        blueprint.route('/search', methods=['GET'])(search)
    blueprint.context_processor(url_for_page_builder)
    blueprint.context_processor(
        lambda: {'site_human_name': site.get_site_human_name()}
    )
    blueprint.context_processor(
        lambda: {'site_human_short_name': site.get_site_human_short_name()}
    )
    return blueprint


docs = Blueprint('docs', __name__, url_prefix='/_marxdown',
                 static_folder='static',
                 template_folder='templates',
                 static_url_path='static')
