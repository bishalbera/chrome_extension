import os
from fastapi import FastAPI, HTTPException
from fastapi.templating import Jinja2Templates
import httpx
from pydantic import BaseModel
from starlette.requests import Request
from starlette.config import Config
from starlette.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi.staticfiles import StaticFiles
from appwrite.client import Client
from appwrite.id import ID
from appwrite.services.databases import Databases

config = Config(".env")
app = FastAPI()
client = Client()

client.set_endpoint("https://cloud.appwrite.io/v1")
client.set_project(config("YOUR_PROJECT_ID"))
client.set_key(config("YOUR_API_KEY"))

databases = Databases(client)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))
app.mount("/static", StaticFiles(directory="static"), name="static")

oauth = OAuth(config)
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_id=config("CLIENT_ID"),
    client_secret=config("CLIENT_SECRET"),
    client_kwargs={
        'scope': 'email openid profile',
        'redirect_url': 'http://localhost:8000/auth'
    }
)


templates = Jinja2Templates(directory="templates")


@app.get("/")
def index(request: Request):
    user = request.session.get('user')
    if user:
        return RedirectResponse('welcome')

    return templates.TemplateResponse(
        name="home.html",
        context={"request": request}
    )


@app.get('/welcome')
def welcome(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse('/')
    return templates.TemplateResponse(
        name='welcome.html',
        context={'request': request, 'user': user}
    )


@app.get("/login")
async def login(request: Request):
    url = request.url_for('auth')
    return await oauth.google.authorize_redirect(request, url)


@app.get('/auth')
async def auth(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        return templates.TemplateResponse(
            name='error.html',
            context={'request': request, 'error': e.error}
        )
    user = token.get('userinfo')
    if user:
        request.session['user'] = dict(user)

    user_data = {
        "user_id": user["sub"],
        "email": user["email"],
        "picture": user["picture"],
        "name": user["name"]
    }

    databases.create_document(
        config("DB_ID"),
        config("COLLECTION_ID"),
        ID.unique(),
        user_data
    )

    return RedirectResponse('welcome')


@app.get('/logout')
def logout(request: Request):
    request.session.pop('user')
    request.session.clear()
    return RedirectResponse('/')

class SearchQuery(BaseModel):
    slug: str

HASHNODE_API_URL = 'https://gql.hashnode.com/'

@app.post("/search-blogs/")
async def search_blogs(query: SearchQuery):
    graphql_query = {
        "query": """
        query Tag($slug: String!, $first: Int!, $filter: TagPostConnectionFilter!) {
          tag(slug: $slug) {
            posts(first: $first, filter: $filter) {
              edges {
                node {
                  title
                  url
                  content {
                    markdown
                  }
                }
              }
            }
          }
        }
        """,
        "variables": {
            "slug": query.slug,
              "first": 10,
                "filter": {"sort"}
            },
    }
    headers = {
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(HASHNODE_API_URL, headers=headers, json=graphql_query)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        data = response.json()
        posts = data.get("data", {}).get("tag", {}).get("posts", {}).get("edges", [])

        slug_word = query.slug.lower()
        extracted_posts = [{"title": post["node"]["title"], "blog_url": post["node"]["url"]} for post in posts if slug_word in post["node"]["title"].lower() ]

        return {"posts": extracted_posts}