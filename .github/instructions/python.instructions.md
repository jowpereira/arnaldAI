---
applyTo: "**/*.py"
description: "Padrões Python para o ArnaldAI — PEP 8, type hints, async patterns e error handling"
---

# Python Coding Standards

Instruções específicas para código Python no ArnaldAI.

## 🎯 Style Guide

### PEP 8 Compliance
- Siga [PEP 8](https://peps.python.org/pep-0008/) rigorosamente
- Use **Ruff** para linting e formatação (88 chars/linha) — `ruff check` + `ruff format`
- Ruff substitui Black, isort e flake8 num único tool

```python
# ✅ Bom
def calculate_total_price(
    items: list[Item],
    discount_rate: float = 0.0,
    tax_rate: float = 0.1,
) -> Decimal:
    """Calculate total price with discount and tax."""
    subtotal = sum(item.price for item in items)
    discounted = subtotal * (1 - discount_rate)
    return Decimal(discounted * (1 + tax_rate))

# ❌ Evitar
def calcTotal(items,discount=0.0,tax=0.1):
    total=0
    for i in items:
        total+=i.price
    return total*(1-discount)*(1+tax)
```

## 📝 Type Hints

### SEMPRE use Type Hints
- Python 3.10+ syntax com `|` para Union
- Use `from __future__ import annotations` para forward references
- Documente tipos complexos com TypedDict ou dataclasses

```python
# ✅ Bom
from __future__ import annotations

from typing import Optional, TypedDict

class UserDict(TypedDict):
    id: str
    name: str
    email: str
    age: Optional[int]

def get_user_by_id(user_id: str) -> User | None:
    """Retrieve user by ID."""
    return user_repository.find(user_id)

def process_users(
    users: list[User],
    *,
    include_inactive: bool = False,
) -> list[UserDict]:
    """Process users and return serialized data."""
    # Implementation
    pass

# ❌ Evitar
def get_user_by_id(user_id):
    return user_repository.find(user_id)
```

### Generics
```python
from typing import Generic, TypeVar

T = TypeVar("T")

class Repository(Generic[T]):
    """Generic repository pattern."""
    
    def __init__(self, model: type[T]) -> None:
        self.model = model
    
    def find_by_id(self, id: str) -> T | None:
        """Find entity by ID."""
        # Implementation
        pass
    
    def find_all(self) -> list[T]:
        """Find all entities."""
        # Implementation
        pass

# Uso
user_repo = Repository[User](User)
user = user_repo.find_by_id("123")
```

## 🏗️ Code Organization

### Imports
- Ordem: stdlib, third-party, local
- Ordem alfabética dentro de cada grupo
- Uma linha por import quando possível

```python
# ✅ Bom
import os
import sys
from datetime import datetime
from typing import Optional

import networkx as nx
import numpy as np
import msgpack

from arnaldo.graph.nodes import NodeKind
from arnaldo.graph.edges import EdgeKind
from arnaldo.graph.provenance import SourceRecord

# ❌ Evitar
from arnaldo.graph.nodes import NodeKind
import sys
import networkx as nx
import numpy as np
from arnaldo.graph.edges import EdgeKind
import os
```

### Estrutura de Módulo
```python
"""
Module docstring explaining purpose.

This module provides user management functionality including
creation, updates, and retrieval operations.
"""

# Imports
from __future__ import annotations

import logging
from typing import Optional

# Constants
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Module-level variables
logger = logging.getLogger(__name__)

# Classes
class UserService:
    """Service for user operations."""
    # Implementation

# Functions
def validate_email(email: str) -> bool:
    """Validate email format."""
    # Implementation

# Main execution guard
if __name__ == "__main__":
    main()
```

## 🎨 Naming Conventions

### Variáveis e Funções
```python
# ✅ Bom - snake_case
user_name = "John Doe"
total_count = 42

def calculate_total_price(items: list[Item]) -> Decimal:
    pass

def get_user_by_email(email: str) -> User | None:
    pass

# ❌ Evitar - camelCase ou PascalCase
userName = "John Doe"
totalCount = 42

def CalculateTotalPrice(items):
    pass
```

### Classes
```python
# ✅ Bom - PascalCase
class UserService:
    pass

class PaymentProcessor:
    pass

class HTTPClient:  # Acrônimos em uppercase
    pass

# ❌ Evitar
class userService:
    pass

class payment_processor:
    pass
```

### Constantes
```python
# ✅ Bom - UPPER_SNAKE_CASE
MAX_RETRY_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 30
API_BASE_URL = "https://api.example.com"

# ❌ Evitar
maxRetryAttempts = 3
default_timeout_seconds = 30
```

### Privado/Protegido
```python
class UserRepository:
    def __init__(self) -> None:
        self._cache: dict[str, User] = {}  # Protected (convenção)
        self.__connection = None  # Private (name mangling)
    
    def get_user(self, user_id: str) -> User | None:
        """Public method."""
        return self._fetch_from_cache(user_id)
    
    def _fetch_from_cache(self, user_id: str) -> User | None:
        """Protected method (internal use)."""
        return self._cache.get(user_id)
```

## 📚 Docstrings

### Google Style (Preferido)
```python
def fetch_user_data(
    user_id: str,
    include_posts: bool = False,
    *,
    timeout: int = 30,
) -> UserData:
    """
    Fetch comprehensive user data from the database.
    
    This function retrieves user information and optionally includes
    their posts. It uses caching to improve performance.
    
    Args:
        user_id: The unique identifier of the user.
        include_posts: Whether to include user's posts in the result.
        timeout: Request timeout in seconds. Defaults to 30.
    
    Returns:
        UserData object containing user information and optional posts.
    
    Raises:
        UserNotFoundError: If the user with given ID doesn't exist.
        DatabaseError: If database connection fails.
        TimeoutError: If request exceeds the timeout duration.
    
    Example:
        >>> user_data = fetch_user_data("user-123", include_posts=True)
        >>> print(user_data.user.name)
        'John Doe'
        >>> print(len(user_data.posts))
        42
    
    Note:
        This function uses an internal cache that expires after 5 minutes.
    """
    # Implementation
```

### Classes
```python
class UserService:
    """
    Service for managing user operations.
    
    This service provides a high-level interface for user-related
    operations including creation, retrieval, updates, and deletion.
    It handles caching and error handling internally.
    
    Attributes:
        repository: The user repository instance.
        cache: Redis cache instance for performance optimization.
        logger: Logger instance for this service.
    
    Example:
        >>> service = UserService(user_repo, cache)
        >>> user = service.create_user("John", "john@example.com")
        >>> print(user.id)
        'user-123'
    """
    
    def __init__(
        self,
        repository: UserRepository,
        cache: Cache,
    ) -> None:
        """
        Initialize the UserService.
        
        Args:
            repository: Repository for user data access.
            cache: Cache instance for optimization.
        """
        self.repository = repository
        self.cache = cache
        self.logger = logging.getLogger(__name__)
```

## 🔧 Best Practices

### Context Managers
```python
# ✅ Bom - Use with statement
with open("data.txt", "r") as file:
    content = file.read()

with db.transaction() as tx:
    tx.execute("INSERT INTO users ...")
    tx.execute("INSERT INTO profiles ...")

# ❌ Evitar
file = open("data.txt", "r")
content = file.read()
file.close()  # Fácil esquecer!
```

### List Comprehensions
```python
# ✅ Bom - Comprehensions para transformações simples
user_ids = [user.id for user in users]
active_users = [user for user in users if user.is_active]
user_dict = {user.id: user.name for user in users}

# ❌ Evitar - Loops quando comprehension é melhor
user_ids = []
for user in users:
    user_ids.append(user.id)

# ⚠️ Cuidado - Comprehensions complexas demais
result = [
    process_item(item, config)
    for category in categories
    for item in category.items
    if item.is_valid and item.price > 0
    and category.is_active
]  # Considere usar loop regular para maior clareza
```

### F-Strings
```python
# ✅ Bom - f-strings
name = "John"
age = 30
message = f"User {name} is {age} years old"
formatted = f"Total: ${total:.2f}"
debug = f"{variable=}"  # Python 3.8+ debug syntax

# ❌ Evitar - format() ou %
message = "User {} is {} years old".format(name, age)
message = "User %s is %d years old" % (name, age)
```

### Dataclasses e Pydantic
```python
from dataclasses import dataclass, field
from datetime import datetime

# ✅ Bom - Dataclass para estruturas simples
@dataclass
class User:
    """User data model."""
    id: str
    name: str
    email: str
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, str] = field(default_factory=dict)

# ✅ Bom - Pydantic para validação
from pydantic import BaseModel, EmailStr, Field

class UserCreateDTO(BaseModel):
    """DTO for user creation."""
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    age: int = Field(..., ge=18, le=120)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "John Doe",
                "email": "john@example.com",
                "age": 30,
            }
        }
```

### Error Handling
```python
# ✅ Bom - Exceções específicas
class UserNotFoundError(Exception):
    """Raised when user is not found."""
    
    def __init__(self, user_id: str, message: str = "") -> None:
        self.user_id = user_id
        super().__init__(message or f"User {user_id} not found")

def get_user(user_id: str) -> User:
    """Get user by ID."""
    try:
        user = db.users.find_one({"id": user_id})
    except DatabaseError as e:
        logger.error(f"Database error fetching user {user_id}", exc_info=True)
        raise
    
    if user is None:
        raise UserNotFoundError(user_id)
    
    return User(**user)

# ❌ Evitar - Bare except ou Exception genérico
try:
    user = get_user(user_id)
except:  # Muito amplo!
    pass

try:
    user = get_user(user_id)
except Exception:  # Ainda muito amplo
    return None
```

### Logging
```python
import logging

logger = logging.getLogger(__name__)

# ✅ Bom - Structured logging
logger.info(
    "User created successfully",
    extra={
        "user_id": user.id,
        "email": user.email,
        "ip_address": request.client.host,
    },
)

logger.error(
    "Failed to process payment",
    exc_info=True,
    extra={
        "user_id": user_id,
        "amount": amount,
        "payment_method": method,
    },
)

# ❌ Evitar - Concatenação de strings
logger.info("User " + user.id + " created")  # Ineficiente
logger.info("User %s created" % user.id)  # Não usar %
```

## ⚡ Performance

### Use Generators
```python
# ✅ Bom - Generator para grandes datasets
def read_large_file(file_path: str):
    """Read file line by line (memory efficient)."""
    with open(file_path, "r") as file:
        for line in file:
            yield line.strip()

# Uso
for line in read_large_file("large.txt"):
    process_line(line)

# ❌ Evitar - Carregar tudo na memória
def read_large_file(file_path: str) -> list[str]:
    with open(file_path, "r") as file:
        return [line.strip() for line in file]  # Pode usar muita RAM
```

### Lazy Evaluation
```python
from typing import Iterator

# ✅ Bom - Iterator
def get_users() -> Iterator[User]:
    """Stream users from database."""
    for user_data in db.users.find():
        yield User(**user_data)

# ❌ Evitar - Carregar todos de uma vez
def get_users() -> list[User]:
    return [User(**data) for data in db.users.find()]  # Pode ser muito grande
```

## 🧪 Testing

### Pytest Style
```python
import pytest
from unittest.mock import Mock, patch

class TestUserService:
    """Test suite for UserService."""
    
    @pytest.fixture
    def user_service(self) -> UserService:
        """Provide a UserService instance for tests."""
        repository = Mock(spec=UserRepository)
        cache = Mock(spec=Cache)
        return UserService(repository, cache)
    
    def test_get_user_returns_user_when_found(
        self,
        user_service: UserService,
    ) -> None:
        """Test that get_user returns user when found in repository."""
        # Arrange
        user_id = "user-123"
        expected_user = User(id=user_id, name="John", email="john@example.com")
        user_service.repository.find_by_id.return_value = expected_user
        
        # Act
        result = user_service.get_user(user_id)
        
        # Assert
        assert result == expected_user
        user_service.repository.find_by_id.assert_called_once_with(user_id)
    
    def test_get_user_raises_error_when_not_found(
        self,
        user_service: UserService,
    ) -> None:
        """Test that get_user raises UserNotFoundError when user not found."""
        # Arrange
        user_id = "invalid-id"
        user_service.repository.find_by_id.return_value = None
        
        # Act & Assert
        with pytest.raises(UserNotFoundError) as exc_info:
            user_service.get_user(user_id)
        
        assert exc_info.value.user_id == user_id
```

---

**Lembre-se**: Python valoriza legibilidade - "Simple is better than complex"!
