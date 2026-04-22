# Project Rules

All contributors must follow these rules. No exceptions.

---

## 1. SSH Keys

Use 4096-bit RSA keys minimum.

```bash
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
```

## 2. Repository Access

Add your public key to every repo you work on. No password authentication.

## 3. Infrastructure as Code

Use **Terraform** for all infrastructure provisioning. No manual resource creation in AWS/cloud consoles.

## 4. Post-Provisioning Configuration

Use **Ansible** for all post-provisioning configuration management. No manual SSH-and-configure workflows.

## 5. Programming Language

Use **Python** as the primary programming language unless the task specifically requires otherwise (e.g., React Native for mobile, MicroPython for ESP32 firmware).

## 7. Naming Convention

Always use underscores (`_`) instead of hyphens (`-`) or spaces when naming files, variables, functions, resources, and identifiers.

```
my_project_name    # correct
my-project-name    # wrong
my project name    # wrong
```

## 8. Documentation

Every project must include:
- `KNOWLEDGE.md` — domain knowledge, research references, and project context
- `RULES.md` — this file; project rules and standards
